import type { FastifyInstance } from "fastify";
import {
  graphAffected,
  graphExplore,
  graphImpact,
  graphRelationships,
  graphResponse,
  graphSearch,
  graphStatus,
  type GraphSearchFilters,
} from "../../graph/operations.js";
import { notFoundError } from "../../errors.js";
import type { HttpRouteContext } from "../context.js";
import {
  isString,
  numberBody,
  numberQuery,
  objectBody,
  optionalString,
  params,
  queryObject,
  withRepo,
  stringField,
} from "../request.js";

export function registerGraphRoutes(
  app: FastifyInstance,
  { store, services }: HttpRouteContext,
): void {
  app.get("/api/repos/:repoId/graph", async (request, reply) => {
    const { repoId } = params(request.params);
    return withRepo(reply, store, repoId, () => graphResponse(store, repoId));
  });

  app.get("/api/repos/:repoId/graph/status", async (request, reply) => {
    const { repoId } = params(request.params);
    return withRepo(reply, store, repoId, () => graphStatus(store, repoId));
  });

  app.get("/api/repos/:repoId/graph/search", async (request, reply) => {
    const { repoId } = params(request.params);
    return withRepo(reply, store, repoId, () => {
      const query = queryObject(request.query);
      return graphSearch(
        store,
        repoId,
        optionalString(query.q) ?? "",
        searchFilters(query),
      );
    });
  });

  app.get("/api/repos/:repoId/graph/callers", async (request, reply) => {
    const { repoId } = params(request.params);
    return withRepo(reply, store, repoId, () => {
      const query = queryObject(request.query);
      return graphRelationships(
        store,
        repoId,
        stringField(query, "symbol"),
        "callers",
        numberQuery(query.limit, 20),
      );
    });
  });

  app.get("/api/repos/:repoId/graph/callees", async (request, reply) => {
    const { repoId } = params(request.params);
    return withRepo(reply, store, repoId, () => {
      const query = queryObject(request.query);
      return graphRelationships(
        store,
        repoId,
        stringField(query, "symbol"),
        "callees",
        numberQuery(query.limit, 20),
      );
    });
  });

  app.get("/api/repos/:repoId/graph/impact", async (request, reply) => {
    const { repoId } = params(request.params);
    return withRepo(reply, store, repoId, () => {
      const query = queryObject(request.query);
      return graphImpact(
        store,
        repoId,
        stringField(query, "symbol"),
        numberQuery(query.depth, 2),
      );
    });
  });

  app.post("/api/repos/:repoId/graph/explore", async (request, reply) => {
    const { repoId } = params(request.params);
    return withRepo(reply, store, repoId, () => {
      const body = objectBody(request.body);
      return graphExplore(
        store,
        repoId,
        stringField(body, "query"),
        numberBody(body.max_nodes, 160),
      );
    });
  });

  app.post("/api/repos/:repoId/graph/affected", async (request, reply) => {
    const { repoId } = params(request.params);
    return withRepo(reply, store, repoId, () => {
      const body = objectBody(request.body);
      const filePaths = Array.isArray(body.file_paths)
        ? body.file_paths.filter(isString)
        : [];
      return graphAffected(store, repoId, filePaths);
    });
  });

  app.get("/api/repos/:repoId/graph/nodes/:nodeId", async (request, reply) => {
    const { repoId, nodeId } = params(request.params);
    return withRepo(reply, store, repoId, () => {
      const graph = store.getGraph(repoId);
      const node = graph.nodes.find((candidate) => candidate.id === nodeId);
      if (!node) {
        throw notFoundError("Node", nodeId);
      }
      return {
        repo_id: repoId,
        node_id: nodeId,
        type: node.type,
        name: node.name,
        file_path: node.file_path,
        adjacent_edge_count: String(
          graph.edges.filter(
            (edge) => edge.source_id === nodeId || edge.target_id === nodeId,
          ).length,
        ),
      };
    });
  });

  app.get("/api/repos/:repoId/communities", async (request, reply) => {
    const { repoId } = params(request.params);
    return withRepo(reply, store, repoId, () =>
      store.listGraphCommunities(repoId).map((community) => ({
        id: community.id,
        name: community.name,
        level: community.level,
        parent_id: community.parent_id,
        rank: community.rank,
        summary: community.summary ?? "",
      })),
    );
  });

  app.post("/api/repos/:repoId/communities/name", async (request, reply) => {
    const { repoId } = params(request.params);
    return withRepo(reply, store, repoId, async () => {
      const body = objectBody(request.body);
      return services.communityNaming.nameCommunities(repoId, {
        maxCommunities: numberBody(body.max_communities, 40),
      });
    });
  });
}

function searchFilters(query: Record<string, unknown>): GraphSearchFilters {
  const filters: GraphSearchFilters = { limit: numberQuery(query.limit, 20) };
  const type = optionalString(query.type);
  const language = optionalString(query.language);
  const path = optionalString(query.path);
  const name = optionalString(query.name);
  if (type) {
    filters.types = [type];
  }
  if (language) {
    filters.languages = [language];
  }
  if (path) {
    filters.pathFilters = [path];
  }
  if (name) {
    filters.nameFilters = [name];
  }
  return filters;
}
