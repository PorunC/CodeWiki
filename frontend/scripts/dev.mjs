import { spawn } from "node:child_process";
import { copyFileSync, existsSync, mkdirSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const env = { ...process.env };

env.CHOKIDAR_USEPOLLING = env.CHOKIDAR_USEPOLLING ?? "true";

if (process.platform === "win32" && !env.ESBUILD_BINARY_PATH) {
  const bundledBinary = join(root, "node_modules", "@esbuild", "win32-x64", "esbuild.exe");
  const localBinary = join(tmpdir(), "codewiki-dev-tools", "esbuild.exe");

  try {
    if (existsSync(bundledBinary)) {
      mkdirSync(dirname(localBinary), { recursive: true });
      if (!existsSync(localBinary) || statSync(localBinary).size !== statSync(bundledBinary).size) {
        copyFileSync(bundledBinary, localBinary);
      }
      env.ESBUILD_BINARY_PATH = localBinary;
    }
  } catch (error) {
    console.warn(`[dev] Could not stage local esbuild binary: ${error}`);
  }
}

const viteBin = join(root, "node_modules", "vite", "bin", "vite.js");
const child = spawn(process.execPath, [viteBin, ...process.argv.slice(2)], {
  cwd: root,
  env,
  stdio: "inherit"
});

child.on("exit", (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }
  process.exit(code ?? 0);
});
