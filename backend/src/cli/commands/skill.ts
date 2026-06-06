import type { Command } from "commander";
import { cpSync, existsSync, mkdirSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { output, runCliAsync } from "../runtime.js";

export function registerSkillCommands(program: Command): void {
  const skill = program
    .command("skill")
    .description("Install CodeWiki agent skills");

  skill
    .command("install")
    .argument("<target>", "Skill target, currently: codex")
    .option("--json", "Print JSON output")
    .action((target: string, options: { json?: boolean }) =>
      runCliAsync(async () => {
        if (target !== "codex") {
          throw new Error(`Unsupported skill target: ${target}`);
        }
        const source = codeWikiSkillSource();
        if (!existsSync(source)) {
          throw new Error(`CodeWiki skill bundle not found: ${source}`);
        }
        const destination = join(codexHome(), "skills", "codewiki");
        mkdirSync(dirname(destination), { recursive: true });
        cpSync(source, destination, { recursive: true, force: true });
        const payload = {
          target,
          status: "installed",
          source,
          destination,
        };
        output(
          options.json,
          payload,
          `Installed CodeWiki skill to ${destination}`,
        );
      }),
    );
}

function codeWikiSkillSource(): string {
  return join(packageRoot(), "skills", "codewiki");
}

function packageRoot(): string {
  return resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
}

function codexHome(): string {
  return process.env.CODEX_HOME || join(homedir(), ".codex");
}
