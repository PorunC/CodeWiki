import { cpSync, existsSync } from "node:fs";
import { resolve } from "node:path";

const source = resolve("src/prompts");
const target = resolve("dist/prompts");

if (existsSync(source)) {
  cpSync(source, target, { recursive: true });
}
