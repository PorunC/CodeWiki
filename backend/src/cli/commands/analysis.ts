import type { Command } from "commander";
import { updatePayloadFromAnalysis } from "../../presenters/payloads.js";
import { resolveRepo } from "../../services/repoResolver.js";
import {
  output,
  runWithContext,
  runWithContextAsync,
  type CliRuntime,
} from "../runtime.js";

export function registerAnalysisCommands(
  program: Command,
  runtime: CliRuntime,
): void {
  program
    .command("analyze")
    .argument(
      "[repo]",
      "Repository id, id prefix, name, path, Git URL, or current directory",
    )
    .option(
      "--force",
      "Accepted for compatibility; analysis always refreshes stored graph data",
    )
    .option(
      "--progress",
      "Accepted for compatibility; progress output is not emitted yet",
    )
    .option(
      "--community-summaries",
      "Accepted for compatibility; summaries are deterministic",
      true,
    )
    .option("--no-community-summaries", "Accepted for compatibility")
    .option("--json", "Print JSON output")
    .action((selector: string | undefined, options: { json?: boolean }) => {
      runWithContext(runtime, ({ store, scanner, services }) => {
        const repo = resolveRepo(store, scanner, selector);
        const result = services.analysis.analyze(repo.id);
        output(
          options.json,
          result,
          `Analysis ${result.status}: ${result.node_count} nodes, ${result.edge_count} edges`,
        );
      });
    });

  program
    .command("update")
    .argument("[repo]", "Repository id, id prefix, name, path, or Git URL")
    .option(
      "--refresh-chunks",
      "Accepted for compatibility; chunks are refreshed by analysis",
      true,
    )
    .option("--no-refresh-chunks", "Accepted for compatibility")
    .option("--regenerate-wiki", "Regenerate wiki pages after updating", true)
    .option("--no-regenerate-wiki", "Skip wiki page regeneration")
    .option(
      "--community-summaries",
      "Accepted for compatibility; summaries are deterministic",
      true,
    )
    .option("--no-community-summaries", "Accepted for compatibility")
    .option("--json", "Print JSON output")
    .action(
      (
        selector: string | undefined,
        options: {
          refreshChunks?: boolean;
          regenerateWiki?: boolean;
          communitySummaries?: boolean;
          json?: boolean;
        },
      ) =>
        runWithContextAsync(runtime, async ({ store, scanner, services }) => {
          const repo = resolveRepo(store, scanner, selector);
          const result = services.analysis.update(repo.id);
          const wikiRegeneration = options.regenerateWiki
            ? await services.wiki.updatePagesWithLlmFallback(repo.id)
            : { requested: false, status: "not_run" };
          const payload = updatePayloadFromAnalysis(result, wikiRegeneration);
          output(
            options.json,
            payload,
            `Update ${result.status}: ${result.node_count} nodes, ${result.edge_count} edges`,
          );
        }),
    );
}
