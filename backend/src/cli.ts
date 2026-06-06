#!/usr/bin/env node
import { Command } from "commander";
import { registerAskCommand } from "./cli/commands/ask.js";
import { registerAnalysisCommands } from "./cli/commands/analysis.js";
import { registerConfigCommands } from "./cli/commands/config.js";
import { registerGraphCommands } from "./cli/commands/graph.js";
import { registerGraphRagCommands } from "./cli/commands/graphrag.js";
import { registerRepoCommands } from "./cli/commands/repos.js";
import { registerSkillCommands } from "./cli/commands/skill.js";
import { registerSystemCommands } from "./cli/commands/system.js";
import { registerWikiCommands } from "./cli/commands/wiki.js";
import { registerLiteCommands } from "./cli/lite.js";
import { createCliRuntime } from "./cli/runtime.js";
import { CODEWIKI_VERSION } from "./version.js";

const program = new Command();
const runtime = createCliRuntime(program);

program
  .name("codewiki")
  .description("CodeWiki TypeScript backend")
  .version(CODEWIKI_VERSION)
  .option(
    "--database-url <url>",
    "SQLite database URL, e.g. sqlite:///./data/codewiki.sqlite3",
  );

registerSystemCommands(program, runtime);
registerLiteCommands(program);
registerRepoCommands(program, runtime);
registerAnalysisCommands(program, runtime);
registerConfigCommands(program);
registerGraphCommands(program, runtime);
registerGraphRagCommands(program, runtime);
registerWikiCommands(program, runtime);
registerAskCommand(program, runtime);
registerSkillCommands(program);

await program.parseAsync(process.argv);
