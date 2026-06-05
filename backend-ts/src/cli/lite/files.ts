import type { Command } from "commander";
import { formatTree, liteAffected, liteFiles } from "../../lite/operations.js";
import {
  output,
  parseLimit,
  readStdinLines,
  runCli,
  type JsonOption,
} from "../runtime.js";

export function registerLiteFileCommands(lite: Command): void {
  lite
    .command("files")
    .argument("[path]", "Repository path", ".")
    .option("--source-only", "Only show source files")
    .option("--tree", "Print a tree instead of a flat list")
    .option("--live", "Scan the file system instead of reading indexed files")
    .option("--json", "Print JSON output")
    .action(
      (
        path: string,
        options: {
          sourceOnly?: boolean;
          tree?: boolean;
          live?: boolean;
        } & JsonOption,
      ) => {
        runCli(() => {
          const payload = liteFiles(path, {
            sourceOnly: Boolean(options.sourceOnly),
            live: Boolean(options.live),
          });
          output(
            options.json,
            payload,
            options.tree
              ? formatTree(payload.root)
              : payload.files
                  .map(
                    (file) =>
                      `${file.path}  ${file.language || "text"}  ${file.size_bytes} bytes`,
                  )
                  .join("\n"),
          );
        });
      },
    );

  lite
    .command("affected")
    .argument("[files...]", "Changed files")
    .option("--path <path>", "Repository path", ".")
    .option("--stdin", "Read changed files from stdin")
    .option("--depth <depth>", "Traversal depth", "5")
    .option("--test-glob <testGlob>", "Accepted for compatibility")
    .option("--json", "Print JSON output")
    .action(
      (
        files: string[],
        options: {
          path?: string;
          stdin?: boolean;
          depth: string;
          testGlob?: string;
        } & JsonOption,
      ) => {
        runCli(() => {
          const stdinFiles = options.stdin ? readStdinLines() : [];
          const payload = liteAffected(
            options.path ?? ".",
            [...files, ...stdinFiles],
            parseLimit(options.depth),
            options.testGlob,
          );
          output(
            options.json,
            payload,
            `Affected files: ${payload.affected_files.length}`,
          );
        });
      },
    );
}
