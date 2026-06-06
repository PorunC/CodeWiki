import type { FastifyInstance } from "fastify";
import { analysisRunResponse } from "../../analysis/analysisService.js";
import { communityNamingPayloadJson } from "../../graph/communityNamingService.js";
import {
  analysisRunPayload,
  updatePayloadFromAnalysis,
} from "../../presenters/payloads.js";
import { notFoundError } from "../../errors.js";
import type { HttpRouteContext } from "../context.js";
import { boolBody, objectBody, params, withRepo } from "../request.js";

export function registerRunRoutes(
  app: FastifyInstance,
  { store, services }: HttpRouteContext,
): void {
  app.post("/api/repos/:repoId/analyze", async (request, reply) => {
    const { repoId } = params(request.params);
    return withRepo(reply, store, repoId, async () => {
      const body = objectBody(request.body);
      const result = await services.analysis.analyze(repoId);
      const payload = analysisRunPayload(result);
      if (boolBody(body.name_communities ?? body.community_summaries, true)) {
        payload.community_naming = communityNamingPayloadJson(
          await services.communityNaming.nameCommunitiesForAnalysis(repoId),
        );
      }
      return payload;
    });
  });

  app.post("/api/repos/:repoId/update", async (request, reply) => {
    const { repoId } = params(request.params);
    return withRepo(reply, store, repoId, async () => {
      const body = objectBody(request.body);
      const result = await services.analysis.update(repoId);
      const wikiRegeneration = boolBody(body.regenerate_wiki, true)
        ? await services.wiki.updatePagesWithLlmFallback(repoId, "en", {
            staleSlugs: result.stale_pages,
          })
        : { requested: false, status: "not_run" };
      const payload = updatePayloadFromAnalysis(result, wikiRegeneration);
      if (boolBody(body.name_communities ?? body.community_summaries, true)) {
        payload.community_naming = communityNamingPayloadJson(
          await services.communityNaming.nameCommunitiesForAnalysis(repoId),
        );
      }
      return payload;
    });
  });

  app.get("/api/repos/:repoId/runs", async (request, reply) => {
    const { repoId } = params(request.params);
    return withRepo(reply, store, repoId, async () =>
      Promise.all(
        (await store.listAnalysisRuns(repoId)).map((run) =>
          analysisRunResponse(store, run.id),
        ),
      ),
    );
  });

  app.get("/api/repos/:repoId/runs/:runId", async (request, reply) => {
    const { repoId, runId } = params(request.params);
    return withRepo(reply, store, repoId, async () => {
      const run = await store.getAnalysisRun(runId);
      if (!run || run.repo_id !== repoId) {
        throw notFoundError("Analysis run", runId);
      }
      return analysisRunResponse(store, runId);
    });
  });
}
