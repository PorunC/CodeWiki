import type { Command } from "commander";
import { retrievalTracePayload } from "../../graphrag/payloads.js";
import {
  firstRepo,
  resolveRegisteredRepo as resolveRepo,
} from "../../services/repoResolver.js";
import {
  displayNumber,
  displayString,
  output,
  parseLimit,
  runWithContextAsync,
  type CliRuntime,
} from "../runtime.js";

export function registerGraphRagCommands(
  program: Command,
  runtime: CliRuntime,
): void {
  const graphrag = program
    .command("graphrag")
    .description("Build and retrieve local source context");

  graphrag
    .command("build")
    .argument("<repo>", "Repository id, id prefix, or name")
    .option(
      "--embeddings",
      "Accepted for compatibility; embeddings are not migrated yet",
    )
    .option("--json", "Print JSON output")
    .action(
      (selector: string, options: { embeddings?: boolean; json?: boolean }) => {
        return runWithContextAsync(runtime, async ({ store, services }) => {
          const repo = resolveRepo(store, selector);
          const payload = await services.graphRag.buildIndex(repo.id, {
            includeEmbeddings: Boolean(options.embeddings),
          });
          output(
            options.json,
            payload,
            `GraphRAG source chunks: ${payload.chunk_count}`,
          );
        });
      },
    );

  graphrag
    .command("retrieve")
    .argument("<query>", "Retrieval query")
    .argument("[repo]", "Repository id, id prefix, or name")
    .option("--limit <limit>", "Maximum chunks", "10")
    .option("--json", "Print JSON output")
    .action(
      (
        query: string,
        selector: string | undefined,
        options: { limit: string; json?: boolean },
      ) => {
        return runWithContextAsync(runtime, async ({ store, services }) => {
          const repo = selector
            ? resolveRepo(store, selector)
            : firstRepo(store);
          const trace = await services.graphRag.retrieve(repo.id, query, {
            limit: parseLimit(options.limit),
          });
          const payload = retrievalTracePayload(trace);
          output(
            options.json,
            payload,
            trace.source_chunks
              .map((chunk) => {
                const score = displayNumber(chunk.score);
                const filePath = displayString(chunk.file_path);
                const line = displayString(chunk.start_line);
                return `${score}\t${filePath}:${line}`;
              })
              .join("\n"),
          );
        });
      },
    );
}
