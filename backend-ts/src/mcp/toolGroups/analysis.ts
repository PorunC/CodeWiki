import { analysisRunResponse } from "../../analysis/analysisService.js";
import { updatePayloadFromAnalysis } from "../../presenters/payloads.js";
import { resolveRepo } from "../../services/repoResolver.js";
import {
  objectSchema,
  boolArg,
  optionalString,
  repoSelectorSchema,
  tool,
  type ToolRuntime,
  type ToolSpec,
} from "../toolkit.js";

export function buildAnalysisTools({
  store,
  scanner,
  services,
}: ToolRuntime): ToolSpec[] {
  return [
    tool(
      "codewiki_analyze",
      "Run TypeScript graph analysis for a registered repo, path, name, or id.",
      objectSchema({ repo: repoSelectorSchema() }),
      (args) =>
        services.analysis.analyze(
          resolveRepo(store, scanner, optionalString(args, "repo")).id,
        ),
    ),
    tool(
      "codewiki_update",
      "Run a TypeScript graph update for a repository.",
      objectSchema({
        repo: repoSelectorSchema(),
        regenerate_wiki: { type: "boolean", default: true },
      }),
      async (args) => {
        const repo = resolveRepo(store, scanner, optionalString(args, "repo"));
        const result = services.analysis.update(repo.id);
        const wikiRegeneration = boolArg(args, "regenerate_wiki", true)
          ? await services.wiki.updatePagesWithLlmFallback(repo.id)
          : { requested: false, status: "not_run" };
        return updatePayloadFromAnalysis(result, wikiRegeneration);
      },
    ),
    tool(
      "codewiki_runs_list",
      "List analysis runs for a repository.",
      objectSchema({ repo: repoSelectorSchema() }),
      (args) => {
        const repo = resolveRepo(store, scanner, optionalString(args, "repo"));
        return store
          .listAnalysisRuns(repo.id)
          .map((run) => analysisRunResponse(store, run.id));
      },
    ),
  ];
}
