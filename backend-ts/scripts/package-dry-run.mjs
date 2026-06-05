#!/usr/bin/env node
import { spawnSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { packageSmokeProcessEnv } from "./package-smoke-env.mjs";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const packageRoot = join(scriptDir, "..");
const workRoot = mkdtempSync(join(tmpdir(), "codewiki-package-dry-run-"));
const npmCacheDir = join(workRoot, "npm-cache");

try {
  const result = spawnSync("npm", ["pack", "--dry-run"], {
    cwd: packageRoot,
    env: packageSmokeProcessEnv(process.env, npmCacheDir),
    encoding: "utf8",
    stdio: "inherit",
  });
  if (result.error) {
    throw result.error;
  }
  process.exitCode = result.status ?? 1;
} finally {
  rmSync(workRoot, { recursive: true, force: true });
}
