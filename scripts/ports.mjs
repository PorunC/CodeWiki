#!/usr/bin/env node
import { spawnSync } from "node:child_process";
import net from "node:net";
import { fileURLToPath } from "node:url";

const DEFAULT_PORTS = [8000, 5173];
const DEFAULT_TIMEOUT_MS = 5_000;

if (isMainModule()) {
  const { checkOnly, ports } = parseArgs(process.argv.slice(2));
  process.exitCode = await runPortCommand({ checkOnly, ports });
}

export async function runPortCommand({ checkOnly, ports }) {
  const occupied = listenerPidsByPort(ports);
  if (!occupied.size) {
    console.log(`No matching listeners on ports ${ports.join(", ")}`);
    return 0;
  }

  if (checkOnly) {
    console.log("Ports are already in use.");
    console.log(formatListenerSummary(occupied));
    return 1;
  }

  await stopListeners(occupied, ports);
  return 0;
}

export function parseArgs(argv) {
  let checkOnly = false;
  const portArgs = [];
  for (const arg of argv) {
    if (arg === "--check") {
      checkOnly = true;
    } else {
      portArgs.push(arg);
    }
  }
  return {
    checkOnly,
    ports: portArgs.length ? portArgs.map(parsePort) : DEFAULT_PORTS
  };
}

export function parsePort(value) {
  const port = Number.parseInt(value ?? "", 10);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error(`Port must be an integer between 1 and 65535, got ${value}`);
  }
  return port;
}

export function listenerPidsByPort(ports) {
  const occupied = new Map();
  for (const port of ports) {
    const pids = listenerPids([port]);
    if (pids.size) {
      occupied.set(port, pids);
    }
  }
  return occupied;
}

export function formatListenerSummary(occupied) {
  return [...occupied.entries()]
    .sort(([left], [right]) => left - right)
    .map(
      ([port, pids]) => `  port ${port}: PID(s) ${[...pids].sort((left, right) => left - right).join(", ")}`
    )
    .join("\n");
}

export async function isPortAvailable(host, port) {
  return new Promise((resolveAvailability) => {
    const server = net.createServer();
    server.once("error", () => resolveAvailability(false));
    server.listen({ host, port }, () => {
      server.close(() => resolveAvailability(true));
    });
  });
}

async function stopListeners(occupied, ports) {
  const currentPid = process.pid;
  const targets = uniqueSignalTargets([...occupied.values()].flatMap((pids) => [...pids]), currentPid);
  for (const target of targets) {
    console.log(`Stopping ${describeSignalTarget(target)}`);
    killTarget(target, "SIGTERM");
  }

  let remaining = await waitForPortsToClear(ports, DEFAULT_TIMEOUT_MS);
  if (!remaining.size) {
    return;
  }

  console.log("Ports are still in use after graceful shutdown; forcing remaining listeners to stop.");
  const forceTargets = uniqueSignalTargets([...remaining.values()].flatMap((pids) => [...pids]), currentPid);
  for (const target of forceTargets) {
    console.log(`Force killing ${describeSignalTarget(target)}`);
    killTarget(target, "SIGKILL");
  }

  remaining = await waitForPortsToClear(ports, 2_000);
  if (remaining.size) {
    console.log("Some ports are still in use.");
    console.log(formatListenerSummary(remaining));
    throw new Error("Failed to stop all matching listeners.");
  }
}

async function waitForPortsToClear(ports, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (true) {
    const remaining = listenerPidsByPort(ports);
    if (!remaining.size || Date.now() >= deadline) {
      return remaining;
    }
    await new Promise((resolveDelay) => setTimeout(resolveDelay, 200));
  }
}

function listenerPids(ports) {
  return process.platform === "win32" ? windowsListenerPids(ports) : posixListenerPids(ports);
}

function windowsListenerPids(ports) {
  const output = run(["netstat", "-ano", "-p", "tcp"]);
  const pids = new Set();
  for (const line of output.split(/\r?\n/)) {
    const parts = line.trim().split(/\s+/);
    if (parts.length < 5 || parts.at(-2)?.toUpperCase() !== "LISTENING") {
      continue;
    }
    const pid = Number.parseInt(parts.at(-1) ?? "", 10);
    if (Number.isInteger(pid) && ports.includes(portFromAddress(parts[1] ?? ""))) {
      pids.add(pid);
    }
  }
  return pids;
}

function posixListenerPids(ports) {
  const pids = new Set();
  for (const port of ports) {
    for (const pid of pidsFromLsof(port)) {
      pids.add(pid);
    }
    for (const pid of pidsFromFuser(port)) {
      pids.add(pid);
    }
  }
  if (!pids.size) {
    for (const pid of pidsFromSsOrNetstat(ports)) {
      pids.add(pid);
    }
  }
  return pids;
}

function pidsFromLsof(port) {
  return numericLines(run(["lsof", "-nP", `-tiTCP:${port}`, "-sTCP:LISTEN"]));
}

function pidsFromFuser(port) {
  const result = spawnQuiet(["fuser", `${port}/tcp`]);
  if (!result) {
    return new Set();
  }
  return parseFuserPids(port, `${result.stdout}\n${result.stderr}`);
}

export function parseFuserPids(port, output) {
  const pids = new Set();
  const portLabel = `${port}/tcp`;
  for (const line of output.split(/\r?\n/)) {
    const stripped = line.trim();
    if (!stripped) {
      continue;
    }
    let tail = stripped;
    if (tail.includes(portLabel)) {
      const parts = tail.split(portLabel);
      tail = parts.at(-1) ?? "";
      tail = tail.includes(":") ? tail.split(":", 2)[1] ?? "" : tail;
    }
    const tokens = tail.trim().split(/\s+/).filter(Boolean);
    if (tokens.length && tokens.every((token) => /^\d+$/.test(token))) {
      for (const token of tokens) {
        pids.add(Number.parseInt(token, 10));
      }
    }
  }
  return pids;
}

function pidsFromSsOrNetstat(ports) {
  const output = run(["ss", "-ltnp"]) || run(["netstat", "-ltnp"]);
  const pids = new Set();
  for (const line of output.split(/\r?\n/)) {
    if (!ports.some((port) => portFromLine(line) === port)) {
      continue;
    }
    for (const match of line.matchAll(/pid=(\d+)/g)) {
      pids.add(Number.parseInt(match[1], 10));
    }
    for (const match of line.matchAll(/\b(\d+)\//g)) {
      pids.add(Number.parseInt(match[1], 10));
    }
  }
  return pids;
}

function numericLines(output) {
  return new Set(
    output
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter((line) => /^\d+$/.test(line))
      .map((line) => Number.parseInt(line, 10))
  );
}

function uniqueSignalTargets(pids, currentPid) {
  const seen = new Set();
  const targets = [];
  for (const pid of pids.filter((candidate) => candidate !== currentPid).sort((left, right) => left - right)) {
    const target = signalTarget(pid);
    const key = `${target.kind}:${target.value}`;
    if (!seen.has(key)) {
      seen.add(key);
      targets.push(target);
    }
  }
  return targets;
}

function signalTarget(pid) {
  if (process.platform === "win32") {
    return { kind: "pid", value: pid };
  }
  const processGroupId = processGroupForPid(pid);
  const currentProcessGroupId = processGroupForPid(process.pid);
  if (processGroupId !== null && processGroupId !== currentProcessGroupId) {
    return { kind: "pgid", value: processGroupId };
  }
  return { kind: "pid", value: pid };
}

function processGroupForPid(pid) {
  const output = run(["ps", "-o", "pgid=", "-p", String(pid)]).trim();
  const pgid = Number.parseInt(output, 10);
  return Number.isInteger(pgid) ? pgid : null;
}

function describeSignalTarget(target) {
  return target.kind === "pgid" ? `process group ${target.value}` : `PID ${target.value}`;
}

function killTarget(target, signal) {
  if (process.platform === "win32") {
    spawnSync("taskkill", ["/PID", String(target.value), "/T", "/F"], { stdio: "ignore" });
    return;
  }
  try {
    process.kill(target.kind === "pgid" ? -target.value : target.value, signal);
  } catch (error) {
    if (error?.code !== "ESRCH") {
      throw error;
    }
  }
}

function portFromAddress(value) {
  const match = value.match(/[:.](\d+)$/);
  return match ? Number.parseInt(match[1], 10) : null;
}

function portFromLine(line) {
  const match = `${line} `.match(/[:.](\d+)\s/);
  return match ? Number.parseInt(match[1], 10) : null;
}

function run(command) {
  const result = spawnQuiet(command);
  return result ? `${result.stdout}\n${result.stderr}` : "";
}

function spawnQuiet(command) {
  const result = spawnSync(command[0], command.slice(1), {
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"]
  });
  return result.error ? null : { stdout: result.stdout ?? "", stderr: result.stderr ?? "" };
}

function isMainModule() {
  return process.argv[1] ? fileURLToPath(import.meta.url) === process.argv[1] : false;
}
