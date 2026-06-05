#!/usr/bin/env node
import { spawn, spawnSync } from "node:child_process";
import { dirname, isAbsolute, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { isPortAvailable } from "./ports.mjs";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const dryRun = process.argv.includes("--dry-run");
const config = {
  npm: process.env.NPM ?? "npm",
  backendDir: resolveFromRoot(process.env.BACKEND_DIR ?? "backend"),
  frontendDir: resolveFromRoot(process.env.FRONTEND_DIR ?? "frontend"),
  backendHost: process.env.BACKEND_HOST ?? "127.0.0.1",
  backendPort: portFromEnv("BACKEND_PORT", 8000),
  frontendPort: portFromEnv("FRONTEND_PORT", 5173),
  backendStaticDir: resolveFromRoot(process.env.BACKEND_STATIC_DIR ?? "backend/static")
};

const children = [];

await main();

async function main() {
  const backend = {
    command: config.npm,
    args: [
      "--prefix",
      config.backendDir,
      "run",
      "dev",
      "--",
      "serve",
      "--host",
      config.backendHost,
      "--port",
      String(config.backendPort),
      "--static-dir",
      config.backendStaticDir
    ]
  };
  const frontend = {
    command: config.npm,
    args: [
      "--prefix",
      config.frontendDir,
      "run",
      "dev",
      "--",
      "--host",
      "127.0.0.1",
      "--port",
      String(config.frontendPort)
    ]
  };

  if (dryRun) {
    console.log(commandLine(backend));
    console.log(commandLine(frontend));
    return;
  }

  const occupied = [];
  if (!(await isPortAvailable(config.backendHost, config.backendPort))) {
    occupied.push(`${config.backendHost}:${config.backendPort}`);
  }
  if (!(await isPortAvailable("127.0.0.1", config.frontendPort))) {
    occupied.push(`127.0.0.1:${config.frontendPort}`);
  }
  if (occupied.length) {
    console.error(`Cannot start dev servers because these address(es) are already in use: ${occupied.join(", ")}`);
    console.error("Run `make kill` to stop existing listeners, or override BACKEND_PORT or FRONTEND_PORT.");
    process.exitCode = 1;
    return;
  }

  console.log(`Starting backend on http://${config.backendHost}:${config.backendPort}`);
  children.push(start(backend));
  console.log(`Starting frontend on http://127.0.0.1:${config.frontendPort}`);
  children.push(start(frontend));
  process.exitCode = await waitForExit(children);
}

function start({ command, args }) {
  return spawn(command, args, {
    cwd: ROOT,
    detached: process.platform !== "win32",
    env: process.env,
    shell: process.platform === "win32",
    stdio: "inherit"
  });
}

async function waitForExit(processes) {
  let shuttingDown = false;
  const shutdown = (signal = "SIGTERM") => {
    if (shuttingDown) {
      return;
    }
    shuttingDown = true;
    for (const child of processes) {
      terminate(child, signal);
    }
  };
  process.once("SIGINT", () => shutdown("SIGINT"));
  process.once("SIGTERM", () => shutdown("SIGTERM"));

  const winner = await Promise.race(
    processes.map(
      (child) =>
        new Promise((resolveExit) => {
          child.once("exit", (code, signal) => resolveExit({ child, code, signal }));
        })
    )
  );
  shutdown();
  await Promise.all(
    processes
      .filter((child) => child !== winner.child && child.exitCode === null)
      .map(
        (child) =>
          new Promise((resolveExit) => {
            child.once("exit", resolveExit);
          })
      )
  );
  return normalizeExitCode(winner.code, winner.signal);
}

function terminate(child, signal) {
  if (child.exitCode !== null || child.pid === undefined) {
    return;
  }
  if (process.platform === "win32") {
    spawnSync("taskkill", ["/PID", String(child.pid), "/T", "/F"], { stdio: "ignore" });
    return;
  }
  try {
    process.kill(-child.pid, signal);
  } catch {
    try {
      process.kill(child.pid, signal);
    } catch {
      // The child may have exited between the status check and the signal.
    }
  }
}

function normalizeExitCode(code, signal) {
  if (typeof code === "number") {
    return code;
  }
  return signal === "SIGINT" || signal === "SIGTERM" ? 0 : 1;
}

function resolveFromRoot(value) {
  return isAbsolute(value) ? value : resolve(ROOT, value);
}

function portFromEnv(name, fallback) {
  const raw = process.env[name];
  if (!raw) {
    return fallback;
  }
  const port = Number.parseInt(raw, 10);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error(`${name} must be an integer between 1 and 65535, got ${raw}`);
  }
  return port;
}

function commandLine({ command, args }) {
  return [command, ...args].map(shellQuote).join(" ");
}

function shellQuote(value) {
  return /^[A-Za-z0-9_./:=@-]+$/.test(value) ? value : JSON.stringify(value);
}
