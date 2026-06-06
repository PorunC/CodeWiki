import type { Command } from "commander";
import { communityNamingPayloadJson } from "../../graph/communityNamingService.js";
import {
  analysisRunPayload,
  updatePayloadFromAnalysis,
} from "../../presenters/payloads.js";
import { resolveRepo } from "../../services/repoResolver.js";
import { output, runWithContextAsync, type CliRuntime } from "../runtime.js";

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
      "Generate LLM community names and summaries when configured",
      true,
    )
    .option("--no-community-summaries", "Accepted for compatibility")
    .option("--json", "Print JSON output")
    .action(
      (
        selector: string | undefined,
        options: { communitySummaries?: boolean; json?: boolean },
      ) => {
        return runWithContextAsync(
          runtime,
          async ({ store, scanner, services }) => {
            const repo = await resolveRepo(store, scanner, selector);
            const result = await services.analysis.analyze(repo.id);
            const payload = analysisRunPayload(result);
            const communityNaming =
              options.communitySummaries === false
                ? null
                : communityNamingPayloadJson(
                    await services.communityNaming.nameCommunitiesForAnalysis(
                      repo.id,
                    ),
                  );
            if (communityNaming) {
              payload.community_naming = communityNaming;
            }
            output(
              options.json,
              payload,
              [
                `Analysis ${result.status}: ${result.node_count} nodes, ${result.edge_count} edges`,
                communityNaming
                  ? `Community summaries: ${communityNamingStatus(communityNaming)}`
                  : "",
              ]
                .filter(Boolean)
                .join("\n"),
            );
          },
        );
      },
    );

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
      "Generate LLM community names and summaries when configured",
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
          const repo = await resolveRepo(store, scanner, selector);
          const result = await services.analysis.update(repo.id);
          const wikiRegeneration = options.regenerateWiki
            ? await services.wiki.updatePagesWithLlmFallback(repo.id, "en", {
                staleSlugs: result.stale_pages,
              })
            : { requested: false, status: "not_run" };
          const payload = updatePayloadFromAnalysis(result, wikiRegeneration);
          const communityNaming =
            options.communitySummaries === false
              ? null
              : communityNamingPayloadJson(
                  await services.communityNaming.nameCommunitiesForAnalysis(
                    repo.id,
                  ),
                );
          if (communityNaming) {
            payload.community_naming = communityNaming;
          }
          output(
            options.json,
            payload,
            [
              `Update ${result.status}: ${result.node_count} nodes, ${result.edge_count} edges`,
              communityNaming
                ? `Community summaries: ${communityNamingStatus(communityNaming)}`
                : "",
            ]
              .filter(Boolean)
              .join("\n"),
          );
        }),
    );
}

function communityNamingStatus(payload: Record<string, unknown>): string {
  return typeof payload.status === "string" ? payload.status : "unknown";
}
