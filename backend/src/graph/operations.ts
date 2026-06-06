import type { CodeWikiStoreApi } from "../db/types.js";
import type { CodeGraphEdge, CodeGraphNode, JsonObject } from "../types.js";

export type GraphSearchFilters = {
  types?: string[];
  languages?: string[];
  pathFilters?: string[];
  nameFilters?: string[];
  limit?: number;
};

export type GraphRelationshipDirection = "callers" | "callees";

export async function graphResponse(
  store: CodeWikiStoreApi,
  repoId: string,
): Promise<JsonObject> {
  const [graph, communities, communityEdges] = await Promise.all([
    store.getGraph(repoId),
    store.listGraphCommunities(repoId),
    store.listGraphCommunityEdges(repoId),
  ]);
  return {
    repo_id: repoId,
    nodes: graph.nodes.map(graphNodePayload),
    edges: graph.edges.map(graphEdgePayload),
    communities: communities.map((community) => ({
      id: community.id,
      name: community.name,
      level: community.level,
      parent_id: community.parent_id,
      rank: community.rank,
      node_ids: community.node_ids,
      summary: community.summary ?? "",
    })),
    community_edges: communityEdges.map((edge) => ({
      id: edge.id,
      source: edge.source_community_id,
      target: edge.target_community_id,
      type: edge.type,
      weight: edge.weight,
      confidence: edge.confidence,
      reason: edge.reason,
      evidence_edge_ids: edge.evidence_edge_ids,
    })),
  };
}

export async function graphStatus(
  store: CodeWikiStoreApi,
  repoId: string,
): Promise<JsonObject> {
  const [graph, chunks] = await Promise.all([
    store.getGraph(repoId),
    store.listCodeChunks(repoId),
  ]);
  return {
    repo_id: repoId,
    file_count: graph.nodes.filter(
      (node) => node.type === "file" || node.type === "config",
    ).length,
    node_count: graph.nodes.length,
    edge_count: graph.edges.length,
    chunk_count: chunks.length,
    nodes_by_type: countBy(graph.nodes, (node) => node.type),
    edges_by_type: countBy(graph.edges, (edge) => edge.type),
    languages: countBy(
      graph.nodes.filter((node) => node.language),
      (node) => node.language ?? "",
    ),
  };
}

export async function graphSearch(
  store: CodeWikiStoreApi,
  repoId: string,
  query: string,
  filters: GraphSearchFilters = {},
): Promise<JsonObject> {
  const results = await store.searchCodeNodes(repoId, query, filters);
  return {
    repo_id: repoId,
    query,
    results: results.map((hit) => ({
      node: graphNodePayload(hit.node),
      score: hit.score,
      reasons: hit.reasons,
    })),
  };
}

export async function graphRelationships(
  store: CodeWikiStoreApi,
  repoId: string,
  symbol: string,
  direction: GraphRelationshipDirection,
  limit: number,
): Promise<JsonObject> {
  const graph = await store.getGraph(repoId);
  const node = findGraphNode(graph.nodes, symbol);
  if (!node) {
    return { repo_id: repoId, symbol, relationships: [] };
  }
  const relationships = graph.edges
    .filter((edge) =>
      direction === "callers"
        ? edge.target_id === node.id
        : edge.source_id === node.id,
    )
    .slice(0, limit)
    .flatMap((edge) => {
      const source = graph.nodes.find(
        (candidate) => candidate.id === edge.source_id,
      );
      const target = graph.nodes.find(
        (candidate) => candidate.id === edge.target_id,
      );
      return source && target
        ? [
            {
              source: graphNodePayload(source),
              target: graphNodePayload(target),
              edge: graphEdgePayload(edge),
            },
          ]
        : [];
    });
  return { repo_id: repoId, symbol, relationships };
}

export async function graphImpact(
  store: CodeWikiStoreApi,
  repoId: string,
  symbol: string,
  depth = 2,
): Promise<JsonObject> {
  const graph = await store.getGraph(repoId);
  const roots = graph.nodes.filter(
    (node) => node.name === symbol || node.id === symbol,
  );
  const nodeIds = new Set(roots.map((node) => node.id));
  const selectedEdges = new Map<string, CodeGraphEdge>();
  let frontier = new Set(nodeIds);
  for (let level = 0; level < depth && frontier.size; level += 1) {
    const next = new Set<string>();
    for (const edge of graph.edges) {
      if (!frontier.has(edge.source_id) && !frontier.has(edge.target_id)) {
        continue;
      }
      selectedEdges.set(edge.id, edge);
      for (const id of [edge.source_id, edge.target_id]) {
        if (!nodeIds.has(id)) {
          nodeIds.add(id);
          next.add(id);
        }
      }
    }
    frontier = next;
  }
  return {
    repo_id: repoId,
    root_ids: roots.map((node) => node.id),
    depth,
    nodes: graph.nodes
      .filter((node) => nodeIds.has(node.id))
      .map(graphNodePayload),
    edges: [...selectedEdges.values()].map(graphEdgePayload),
  };
}

export async function graphAffected(
  store: CodeWikiStoreApi,
  repoId: string,
  filePaths: string[],
): Promise<JsonObject> {
  const graph = await store.getGraph(repoId);
  const affectedNodeIds = graph.nodes
    .filter((node) => filePaths.includes(node.file_path))
    .map((node) => node.id);
  return {
    repo_id: repoId,
    changed_files: filePaths,
    affected_files: [...new Set(filePaths)],
    affected_tests: [],
    affected_wiki_pages: [],
    affected_node_ids: affectedNodeIds,
    traversed_file_count: filePaths.length,
  };
}

export async function graphExplore(
  store: CodeWikiStoreApi,
  repoId: string,
  query: string,
  maxNodes: number,
  maxFiles = 8,
): Promise<JsonObject> {
  const [hits, chunkHits] = await Promise.all([
    store.searchCodeNodes(repoId, query, { limit: maxNodes }),
    store.searchCodeChunks(repoId, query, maxFiles),
  ]);
  const sourceSections = chunkHits.map((hit) => ({
    file_path: hit.chunk.file_path,
    start_line: hit.chunk.start_line,
    end_line: hit.chunk.end_line,
    content: hit.chunk.content,
  }));
  return {
    repo_id: repoId,
    query,
    entry_points: hits.slice(0, 8).map((hit) => graphNodePayload(hit.node)),
    relationships: [],
    source_sections: sourceSections,
    additional_files: [],
    text: hits.length
      ? `Found ${hits.length} matching graph nodes.`
      : "No graph nodes matched.",
    stats: {
      node_count: hits.length,
      edge_count: 0,
      file_count: sourceSections.length,
    },
  };
}

export async function graphTrace(
  store: CodeWikiStoreApi,
  repoId: string,
  fromSymbol: string,
  toSymbol: string,
  maxDepth: number,
): Promise<JsonObject> {
  const graph = await store.getGraph(repoId);
  const start = findGraphNode(graph.nodes, fromSymbol);
  const target = findGraphNode(graph.nodes, toSymbol);
  if (!start || !target) {
    return {
      repo_id: repoId,
      from_symbol: fromSymbol,
      to_symbol: toSymbol,
      found: false,
      nodes: [],
      edges: [],
      text: `Trace endpoints not found: ${!start ? fromSymbol : toSymbol}`,
    };
  }

  const queue: Array<{ nodeId: string; pathEdges: CodeGraphEdge[] }> = [
    { nodeId: start.id, pathEdges: [] },
  ];
  const visited = new Set([start.id]);
  while (queue.length) {
    const current = queue.shift();
    if (!current) {
      break;
    }
    if (current.nodeId === target.id) {
      const nodeIds = new Set([
        start.id,
        target.id,
        ...current.pathEdges.flatMap((edge) => [
          edge.source_id,
          edge.target_id,
        ]),
      ]);
      const nodes = graph.nodes.filter((node) => nodeIds.has(node.id));
      return {
        repo_id: repoId,
        from_symbol: fromSymbol,
        to_symbol: toSymbol,
        found: true,
        nodes: nodes.map(graphNodePayload),
        edges: current.pathEdges.map(graphEdgePayload),
        text: `Trace found: ${nodes.map((node) => node.name).join(" -> ")}`,
      };
    }
    if (current.pathEdges.length >= maxDepth) {
      continue;
    }
    for (const edge of graph.edges.filter(
      (candidate) =>
        candidate.source_id === current.nodeId ||
        candidate.target_id === current.nodeId,
    )) {
      const nextNodeId =
        edge.source_id === current.nodeId ? edge.target_id : edge.source_id;
      if (visited.has(nextNodeId)) {
        continue;
      }
      visited.add(nextNodeId);
      queue.push({
        nodeId: nextNodeId,
        pathEdges: [...current.pathEdges, edge],
      });
    }
  }

  return {
    repo_id: repoId,
    from_symbol: fromSymbol,
    to_symbol: toSymbol,
    found: false,
    nodes: [graphNodePayload(start), graphNodePayload(target)],
    edges: [],
    text: `No trace found from ${fromSymbol} to ${toSymbol}.`,
  };
}

export async function graphNodeContext(
  store: CodeWikiStoreApi,
  repoId: string,
  symbol: string,
): Promise<JsonObject> {
  const graph = await store.getGraph(repoId);
  const node = findGraphNode(graph.nodes, symbol);
  if (!node) {
    throw new Error(`Graph node not found: ${symbol}`);
  }
  const adjacentEdges = graph.edges.filter(
    (edge) => edge.source_id === node.id || edge.target_id === node.id,
  );
  const adjacentIds = new Set(
    adjacentEdges.flatMap((edge) => [edge.source_id, edge.target_id]),
  );
  return {
    repo_id: repoId,
    node: graphNodePayload(node),
    adjacent_nodes: graph.nodes
      .filter(
        (candidate) =>
          adjacentIds.has(candidate.id) && candidate.id !== node.id,
      )
      .map(graphNodePayload),
    adjacent_edges: adjacentEdges.map(graphEdgePayload),
    source_sections: (await store.listCodeChunks(repoId))
      .filter((chunk) => chunk.file_path === node.file_path)
      .slice(0, 3),
  };
}

export async function graphNodeRead(
  store: CodeWikiStoreApi,
  repoId: string,
  nodeId: string,
): Promise<JsonObject> {
  const graph = await store.getGraph(repoId);
  const node = graph.nodes.find((candidate) => candidate.id === nodeId);
  if (!node) {
    throw new Error(`Node not found: ${nodeId}`);
  }
  const adjacentEdges = graph.edges.filter(
    (edge) => edge.source_id === nodeId || edge.target_id === nodeId,
  );
  return {
    repo_id: repoId,
    node: graphNodePayload(node),
    adjacent_edges: adjacentEdges.map(graphEdgePayload),
  };
}

export async function graphCommunitiesList(
  store: CodeWikiStoreApi,
  repoId: string,
): Promise<JsonObject[]> {
  return (await store.listGraphCommunities(repoId)).map((community) => ({
    id: community.id,
    repo_id: community.repo_id,
    name: community.name,
    level: community.level,
    parent_id: community.parent_id,
    rank: community.rank,
    node_ids: community.node_ids,
    summary: community.summary ?? "",
    summary_hash: community.summary_hash,
    created_at: community.created_at,
  }));
}

export function graphNodePayload(node: CodeGraphNode): JsonObject {
  return {
    id: node.id,
    type: node.type,
    name: node.name,
    file_path: node.file_path,
    start_line: node.start_line,
    end_line: node.end_line,
    language: node.language,
    symbol_id: node.symbol_id,
    confidence: 1,
    provenance: isJsonObject(node.metadata.provenance)
      ? node.metadata.provenance
      : {},
    metadata: node.metadata,
  };
}

export function graphEdgePayload(edge: CodeGraphEdge): JsonObject {
  return {
    id: edge.id,
    source: edge.source_id,
    target: edge.target_id,
    type: edge.type,
    confidence: edge.confidence,
    confidence_level:
      typeof edge.metadata.confidence_level === "string"
        ? edge.metadata.confidence_level
        : null,
    reason:
      typeof edge.metadata.reason === "string" ? edge.metadata.reason : null,
    is_inferred: edge.is_inferred,
    provenance: isJsonObject(edge.metadata.provenance)
      ? edge.metadata.provenance
      : {},
    metadata: edge.metadata,
  };
}

function findGraphNode(
  nodes: CodeGraphNode[],
  symbol: string,
): CodeGraphNode | null {
  return (
    nodes.find(
      (node) =>
        node.id === symbol || node.name === symbol || node.symbol_id === symbol,
    ) ?? null
  );
}

function countBy<T>(items: T[], key: (item: T) => string): JsonObject {
  const result: Record<string, number> = {};
  for (const item of items) {
    const value = key(item);
    result[value] = (result[value] ?? 0) + 1;
  }
  return result;
}

function isJsonObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
