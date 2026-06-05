import type { Command } from "commander";
import { liteDatabasePath, uninitLiteRepo } from "../../lite.js";
import {
  liteIndex,
  liteInit,
  liteStatus,
  liteSync,
} from "../../lite/operations.js";
import { output, runCli, runCliAsync, type JsonOption } from "../runtime.js";

export function registerLiteLifecycleCommands(lite: Command): void {
  lite
    .command("init")
    .argument("[path]", "Repository path", ".")
    .option("--name <name>", "Repository display name")
    .option("--json", "Print JSON output")
    .action((path: string, options: { name?: string } & JsonOption) => {
      runCli(() => {
        const payload = liteInit(path, options.name);
        output(
          options.json,
          payload,
          `Initialized lite index for ${payload.repo.name}\n${payload.database_path}`,
        );
      });
    });

  lite
    .command("uninit")
    .argument("[path]", "Repository path", ".")
    .option("--force", "Remove the lite index without prompting")
    .option("--json", "Print JSON output")
    .action((path: string, options: { force?: boolean } & JsonOption) => {
      runCli(() => {
        if (!options.force) {
          throw new Error("Pass --force to remove a lite index.");
        }
        const databasePath = liteDatabasePath(path);
        const deleted = uninitLiteRepo(path);
        const payload = { database_path: databasePath, deleted };
        output(
          options.json,
          payload,
          deleted
            ? `Removed ${databasePath}`
            : `No lite index found at ${databasePath}`,
        );
      });
    });

  lite
    .command("index")
    .argument("[path]", "Repository path", ".")
    .option("--name <name>", "Repository display name")
    .option("--force", "Force a full rebuild")
    .option("--json", "Print JSON output")
    .action(
      (
        path: string,
        options: { name?: string; force?: boolean } & JsonOption,
      ) => {
        return runCliAsync(async () => {
          const indexOptions: { name?: string; force?: boolean } = {};
          if (options.name) {
            indexOptions.name = options.name;
          }
          if (options.force !== undefined) {
            indexOptions.force = options.force;
          }
          const payload = await liteIndex(path, indexOptions);
          output(
            options.json,
            payload,
            `Lite index ${payload.status}: ${payload.node_count} nodes, ${payload.edge_count} edges\n${payload.database_path}`,
          );
        });
      },
    );

  lite
    .command("sync")
    .argument("[path]", "Repository path", ".")
    .option("--json", "Print JSON output")
    .action((path: string, options: JsonOption) => {
      return runCliAsync(async () => {
        const payload = await liteSync(path);
        output(
          options.json,
          payload,
          `Lite sync ${payload.status}: ${payload.node_count} nodes, ${payload.edge_count} edges`,
        );
      });
    });

  lite
    .command("status")
    .argument("[path]", "Repository path", ".")
    .option("--json", "Print JSON output")
    .action((path: string, options: JsonOption) => {
      runCli(() => {
        const payload = liteStatus(path);
        output(
          options.json,
          payload,
          `${payload.node_count} nodes, ${payload.edge_count} edges, ${payload.file_count} files\n${payload.database_path}`,
        );
      });
    });
}
