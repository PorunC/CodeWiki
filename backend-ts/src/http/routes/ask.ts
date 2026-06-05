import type { FastifyInstance } from "fastify";
import type { HttpRouteContext } from "../context.js";
import {
  boolBody,
  numberBody,
  objectBody,
  params,
  stringField,
  withRepo,
} from "../request.js";

export function registerAskRoutes(
  app: FastifyInstance,
  { store, services }: HttpRouteContext,
): void {
  app.post("/api/repos/:repoId/ask", async (request, reply) => {
    const { repoId } = params(request.params);
    return withRepo(reply, store, repoId, () => {
      const body = objectBody(request.body);
      return services.questionAnswerer.answerWithLlmFallback(repoId, {
        question: stringField(body, "question"),
        max_hops: numberBody(body.max_hops, 2),
        include_sources: boolBody(body.include_sources, true),
        include_graph: boolBody(body.include_graph, true),
      });
    });
  });
}
