import type { FastifyInstance } from "fastify";
import { notFoundError } from "../../errors.js";
import { retrievalTracePayload } from "../../graphrag/payloads.js";
import type { HttpRouteContext } from "../context.js";
import {
  boolBody,
  numberBody,
  objectBody,
  params,
  stringField,
  withRepo,
} from "../request.js";

export function registerGraphRagRoutes(
  app: FastifyInstance,
  { store, services }: HttpRouteContext,
): void {
  app.post("/api/repos/:repoId/graphrag/build", async (request, reply) => {
    const { repoId } = params(request.params);
    return withRepo(reply, store, repoId, () => {
      const body = objectBody(request.body);
      return services.graphRag.buildIndex(repoId, {
        includeEmbeddings: boolBody(body.include_embeddings, false),
      });
    });
  });

  app.post("/api/repos/:repoId/graphrag/retrieve", async (request, reply) => {
    const { repoId } = params(request.params);
    return withRepo(reply, store, repoId, async () => {
      const body = objectBody(request.body);
      const trace = await services.graphRag.retrieve(
        repoId,
        stringField(body, "query"),
        {
          maxHops: numberBody(body.max_hops, 2),
          limit: numberBody(body.limit, 10),
          includeEmbeddings: boolBody(body.include_embeddings, false),
        },
      );
      return retrievalTracePayload(trace);
    });
  });

  app.get(
    "/api/repos/:repoId/graphrag/traces/:traceId",
    async (request, reply) => {
      const { repoId, traceId } = params(request.params);
      return withRepo(reply, store, repoId, async () => {
        const trace = await store.getRetrievalTrace(repoId, traceId);
        if (!trace) {
          throw notFoundError("GraphRAG trace", traceId);
        }
        return retrievalTracePayload(trace);
      });
    },
  );
}
