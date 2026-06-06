import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const PROMPTS_DIR = resolve(
  dirname(fileURLToPath(import.meta.url)),
  "../prompts",
);

export function loadPrompt(name: string): string {
  if (!/^[a-z0-9_-]+\.md$/i.test(name)) {
    throw new Error(`Invalid prompt name: ${name}`);
  }
  return readFileSync(resolve(PROMPTS_DIR, name), "utf8");
}
