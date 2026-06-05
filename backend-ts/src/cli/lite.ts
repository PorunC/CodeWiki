import type { Command } from "commander";
import { registerLiteFileCommands } from "./lite/files.js";
import { registerLiteGraphCommands } from "./lite/graph.js";
import { registerLiteLifecycleCommands } from "./lite/lifecycle.js";

export function registerLiteCommands(program: Command): void {
  const lite = program
    .command("lite")
    .description(
      "Use a project-local, no-LLM CodeWiki index for agent workflows",
    );

  registerLiteLifecycleCommands(lite);
  registerLiteGraphCommands(lite);
  registerLiteFileCommands(lite);
}
