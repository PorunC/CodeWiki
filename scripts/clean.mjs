#!/usr/bin/env node
import { existsSync, rmSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");

export const CLEAN_PATHS = [
  ".pytest_cache",
  ".ruff_cache",
  "backend/dist",
  "backend/coverage",
  "backend/static",
  "frontend/dist",
  "frontend/.vite",
  "frontend/tsconfig.tsbuildinfo"
];

export function clean(paths = CLEAN_PATHS, root = ROOT) {
  const removed = [];
  for (const relativePath of paths) {
    const target = resolve(root, relativePath);
    if (!existsSync(target)) {
      continue;
    }
    rmSync(target, { recursive: true, force: true });
    removed.push(relativePath);
  }
  return removed;
}

if (isMainModule()) {
  const removed = clean();
  if (removed.length) {
    console.log(`Removed ${removed.join(", ")}`);
  } else {
    console.log("No build artifacts to remove.");
  }
}

function isMainModule() {
  return process.argv[1] ? fileURLToPath(import.meta.url) === process.argv[1] : false;
}
