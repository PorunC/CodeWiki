import type { FastifyInstance } from "fastify";
import { analysisRunResponse } from "../../analysis/analysisService.js";
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
      const result = await services.analysis.analyze(repoId);
      return analysisRunPayload(result);
    });
  });

  app.post("/api/repos/:repoId/update", async (request, reply) => {
    const { repoId } = params(request.params);
    return withRepo(reply, store, repoId, async () => {
      const body = objectBody(request.body);
      const result = await services.analysis.update(repoId);
      const wikiRegeneration = boolBody(body.regenerate_wiki, true)
        ? await services.wiki.updatePagesWithLlmFallback(repoId)
        : { requested: false, status: "not_run" };
      return updatePayloadFromAnalysis(result, wikiRegeneration);
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
