#!/usr/bin/env node
import { spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { delimiter, dirname, isAbsolute, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");

export function frontendNpmCommand(argv, env = process.env) {
  const npm = env.NPM ?? "npm";
  const npmPath = findExecutable(npm, env) ?? npm;
  const frontendDir = resolveFromRoot(env.FRONTEND_DIR ?? "frontend");

  if (isWsl() && isWindowsToolOnWsl(npmPath)) {
    return {
      ok: false,
      frontendDir,
      message: [
        `Windows npm was found first on PATH: ${npmPath}`,
        "This repository is inside the WSL filesystem, so frontend dependencies must be managed with Linux npm.",
        "Install Node.js/npm inside WSL, remove Windows Node from the WSL PATH, or pass NPM=/path/to/linux/npm.",
        "",
        "Examples:",
        "  sudo apt install nodejs npm",
        "  make install-frontend",
        "  make start"
      ].join("\n")
    };
  }

  if (process.platform === "win32" && npmPath.toLowerCase().endsWith(".ps1")) {
    return {
      ok: true,
      frontendDir,
      command: "powershell.exe",
      args: ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", npmPath, ...argv]
    };
  }

  return {
    ok: true,
    frontendDir,
    command: npmPath,
    args: argv
  };
}

export function resolveFromRoot(value) {
  return isAbsolute(value) ? resolve(value) : resolve(ROOT, value);
}

export function isWsl() {
  if (process.platform !== "linux") {
    return false;
  }
  try {
    const version = readFileSync("/proc/version", "utf8").toLowerCase();
    return version.includes("microsoft") || version.includes("wsl");
  } catch {
    return false;
  }
}

export function isWindowsToolOnWsl(path) {
  const normalized = path.replaceAll("\\", "/").toLowerCase();
  return normalized.startsWith("/mnt/") || /\.(exe|cmd|bat|ps1)$/.test(normalized);
}

function findExecutable(command, env) {
  if (command.includes("/") || command.includes("\\")) {
    return existsSync(command) ? command : null;
  }

  const pathValue = env.PATH ?? "";
  const extensions =
    process.platform === "win32"
      ? (env.PATHEXT ?? ".COM;.EXE;.BAT;.CMD;.PS1").split(";")
      : [""];

  for (const directory of pathValue.split(delimiter).filter(Boolean)) {
    for (const extension of extensions) {
      const candidate = join(directory, `${command}${extension}`);
      if (existsSync(candidate)) {
        return candidate;
      }
    }
    const candidate = join(directory, command);
    if (existsSync(candidate)) {
      return candidate;
    }
  }
  return null;
}

if (isMainModule()) {
  const command = frontendNpmCommand(process.argv.slice(2));
  if (!command.ok) {
    console.error(command.message);
    process.exitCode = 127;
  } else {
    const result = spawnSync(command.command, command.args, {
      cwd: command.frontendDir,
      stdio: "inherit"
    });
    if (result.error) {
      throw result.error;
    }
    process.exitCode = result.status ?? 1;
  }
}

function isMainModule() {
  return process.argv[1] ? fileURLToPath(import.meta.url) === process.argv[1] : false;
}
