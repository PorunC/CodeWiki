import { createHash } from "node:crypto";
import type { CodeWikiStoreApi } from "../db/types.js";
import { notFoundError, validationError } from "../errors.js";
import {
  filterWikiGraph,
  isWikiNoiseFile,
  isWikiNoiseNode,
} from "../services/fileRoles.js";
import type {
  CodeChunk,
  CodeGraphEdge,
  CodeGraphNode,
  GraphCommunity,
  JsonObject,
  RetrievalTrace,
} from "../types.js";
import type { CodeChunkHit } from "./embeddingIndex.js";
import {
  communityEdgeRetrievalPayload,
  communityRetrievalPayload,
  edgeRetrievalPayload,
  nodeRetrievalPayload,
  sourceChunkPayload,
} from "./payloads.js";
import {
  DEFAULT_GRAPHRAG_CONTEXT_TOKEN_BUDGET,
  DEFAULT_GRAPHRAG_MAX_SOURCE_CHUNKS,
} from "./defaults.js";
import { buildSourceChunks } from "./chunkBuilder.js";

export type RetrievalOptions = {
  maxHops?: number;
  limit?: number;
  contextTokenBudget?: number;
  includeEmbeddings?: boolean;
  chunkHits?: CodeChunkHit[];
};

type NodeHit = {
  nodeId: string;
  score: number;
  reasons: Set<string>;
};

type RankedChunkHit = {
  chunk: CodeChunk;
  score: number;
  reasons: Set<string>;
  scoreComponents: Record<string, number>;
  matchType: string;
};

const SOURCE_NODE_TYPES = new Set([
  "file",
  "config",
  "class",
  "function",
  "method",
  "schema",
  "endpoint",
]);
const SEED_NODE_TYPES = new Set([...SOURCE_NODE_TYPES, "module"]);
const EDGE_WEIGHTS: Record<string, number> = {
  calls: 1,
  routes_to: 1,
  inherits: 0.9,
  implements: 0.86,
  imports: 0.82,
  exports: 0.78,
  references: 0.7,
  uses_config: 0.66,
  defines: 0.72,
  contains: 0.58,
};
const HYBRID_RANKING_WEIGHTS = {
  semantic: 0.35,
  keyword: 0.25,
  graph_proximity: 0.2,
  node_importance: 0.1,
  source_freshness: 0.1,
};
const MAX_SEED_NODES = 12;
const MAX_EXPANDED_NODES = 60;
const MAX_RELATED_EDGES = 140;
const MAX_COMMUNITY_SUMMARIES = 12;
const MAX_PARENT_SUMMARIES = 3;
const MAX_CHILD_SUMMARIES = 8;
const MAX_CHILDREN_PER_PARENT_IN_PROMPT = 4;
const MAX_COMMUNITY_EDGES = 16;
const TOKEN_RE = /[A-Za-z_][A-Za-z0-9_]*|[0-9]+/g;

export async function buildRetrievalTrace(
  store: CodeWikiStoreApi,
  repoId: string,
  query: string,
  options: RetrievalOptions = {},
): Promise<RetrievalTrace> {
  const repo = await store.getRepo(repoId);
  if (!repo) {
    throw notFoundError("Repository", repoId);
  }
  const normalizedQuery = query.trim() || "repository overview";
  const maxSourceChunks = positiveInt(
    options.limit,
    DEFAULT_GRAPHRAG_MAX_SOURCE_CHUNKS,
  );
  const contextTokenBudget = positiveInt(
    options.contextTokenBudget,
    DEFAULT_GRAPHRAG_CONTEXT_TOKEN_BUDGET,
  );
  const maxHops = boundedInt(options.maxHops, 2, 0, 4);
  const rawGraph = await store.getGraph(repoId);
  if (!rawGraph.nodes.length) {
    throw validationError("Run analysis before GraphRAG retrieval.");
  }
  const graph = filterWikiGraph(rawGraph.nodes, rawGraph.edges);
  const nodeById = new Map(graph.nodes.map((node) => [node.id, node]));
  let allChunks = await store.listCodeChunks(repoId);
  if (!allChunks.length) {
    allChunks = buildSourceChunks(repoId, repo.path, rawGraph.nodes);
    await store.replaceCodeChunks(repoId, allChunks);
  }
  const chunkHits =
    options.chunkHits ??
    (await store.searchCodeChunks(repoId, normalizedQuery, maxSourceChunks));

  const seedHits = await seedFromSymbols(
    store,
    repoId,
    normalizedQuery,
    graph.nodes,
  );
  mergeChunkHitsIntoSeeds(seedHits, chunkHits, nodeById);
  if (!seedHits.size) {
    addOverviewFallbackSeeds(seedHits, graph.nodes);
  }

  const seedEntries = [...seedHits.entries()]
    .sort((left, right) => right[1].score - left[1].score)
    .slice(0, MAX_SEED_NODES);
  const selectedSeedHits = new Map(seedEntries);
  const { selectedIds, hops, scores } = expand(
    selectedSeedHits,
    graph.edges,
    maxHops,
  );
  const selectedEdges = relatedEdges(graph.edges, selectedIds);
  const rankedSourceChunks = selectSourceChunks({
    chunks: allChunks,
    chunkHits,
    nodes: graph.nodes,
    edges: graph.edges,
    selectedIds,
    seedIds: new Set(selectedSeedHits.keys()),
    hops,
    maxSourceChunks,
    contextTokenBudget,
  });
  const communities = await communitySummaries(store, repoId, selectedIds);
  const communityIds = new Set(
    communities
      .map((community) => stringValue(community.id))
      .filter((id): id is string => Boolean(id)),
  );
  const communityEdges = (await store.listGraphCommunityEdges(repoId))
    .filter(
      (edge) =>
        communityIds.has(edge.source_community_id) &&
        communityIds.has(edge.target_community_id),
    )
    .slice(0, MAX_COMMUNITY_EDGES);

  const seedNodes = seedEntries.flatMap(([nodeId, hit]) => {
    const node = nodeById.get(nodeId);
    return node
      ? [nodeRetrievalPayload(node, hit.score, [...hit.reasons].sort(), 0)]
      : [];
  });
  const expandedNodes = [...selectedIds]
    .filter((nodeId) => !selectedSeedHits.has(nodeId))
    .sort(
      (left, right) =>
        (hops.get(left) ?? 0) - (hops.get(right) ?? 0) ||
        left.localeCompare(right),
    )
    .flatMap((nodeId) => {
      const node = nodeById.get(nodeId);
      return node
        ? [
            nodeRetrievalPayload(
              node,
              scores.get(nodeId) ?? 0,
              ["graph_expansion"],
              hops.get(nodeId) ?? 1,
            ),
          ]
        : [];
    });
  const edgePayloads = selectedEdges.map(edgeRetrievalPayload);
  const sourceChunks = rankedSourceChunks.map((hit, index) =>
    sourceChunkPayload(hit.chunk, hit.score, hit.matchType, index, {
      reasons: [...hit.reasons],
      scoreComponents: hit.scoreComponents,
    }),
  );
  const communityEdgePayloads = communityEdges.map(
    communityEdgeRetrievalPayload,
  );
  const nodes = [...seedNodes, ...expandedNodes];
  const contextPack = contextPackPayload({
    query: normalizedQuery,
    chunks: rankedSourceChunks,
    relatedEdges: edgePayloads,
    nodes,
    communities,
    communityEdges: communityEdgePayloads,
  });
  const context = stringValue(contextPack.text) ?? "";

  return {
    repo_id: repoId,
    query: normalizedQuery,
    max_hops: maxHops,
    trace_id: traceId(
      repoId,
      normalizedQuery,
      [...selectedSeedHits.keys()],
      rankedSourceChunks.map((hit) => hit.chunk.id),
    ),
    seed_nodes: seedNodes,
    expanded_nodes: expandedNodes,
    source_chunks: sourceChunks,
    related_edges: edgePayloads,
    community_summaries: communities,
    community_edges: communityEdgePayloads,
    context_pack: contextPack,
    chunks: rankedSourceChunks.map((hit) => hit.chunk),
    nodes,
    edges: edgePayloads,
    communities,
    context,
    created_at: null,
  };
}

async function seedFromSymbols(
  store: CodeWikiStoreApi,
  repoId: string,
  query: string,
  nodes: CodeGraphNode[],
): Promise<Map<string, NodeHit>> {
  const queryLower = query.toLowerCase();
  const queryTerms = new Set(terms(query));
  const hits = new Map<string, NodeHit>();
  if (!queryTerms.size && !queryLower) {
    return hits;
  }

  for (const searchHit of await store.searchCodeNodes(repoId, query, {
    types: [...SEED_NODE_TYPES].sort(),
    limit: 32,
  })) {
    if (isWikiNoiseNode(searchHit.node)) {
      continue;
    }
    hits.set(searchHit.node.id, {
      nodeId: searchHit.node.id,
      score: Math.min(1.3, Math.max(0.35, searchHit.score)),
      reasons: new Set([...searchHit.reasons, "symbol_fts"]),
    });
  }

  for (const node of nodes) {
    if (isWikiNoiseNode(node) || !SEED_NODE_TYPES.has(node.type)) {
      continue;
    }
    const haystack = nodeHaystack(node);
    const nameLower = node.name.toLowerCase();
    const nameTerms = new Set(terms(node.name));
    let score = 0;
    if (nameLower === queryLower) {
      score = 1.15;
    } else if (queryTerms.has(nameLower)) {
      score = 1.05;
    } else if (queryLower && haystack.includes(queryLower)) {
      score = 0.88;
    } else if (nameLower && queryLower.includes(nameLower)) {
      score = 0.82;
    }
    const sharedTerms = intersectionSize(queryTerms, nameTerms);
    if (sharedTerms) {
      score = Math.max(score, 0.55 + sharedTerms * 0.12);
    }
    if (!score && [...queryTerms].some((term) => haystack.includes(term))) {
      score = 0.42;
    }
    if (!score) {
      continue;
    }
    score += nodeTypeBoost(node.type);
    const existing = hits.get(node.id);
    if (existing) {
      existing.score = Math.max(existing.score, Math.min(score, 1.25));
      existing.reasons.add("symbol");
    } else {
      hits.set(node.id, {
        nodeId: node.id,
        score: Math.min(score, 1.25),
        reasons: new Set(["symbol"]),
      });
    }
  }
  return hits;
}

function mergeChunkHitsIntoSeeds(
  seedHits: Map<string, NodeHit>,
  chunkHits: CodeChunkHit[],
  nodeById: Map<string, CodeGraphNode>,
): void {
  const fileNodesByPath = new Map(
    [...nodeById.values()]
      .filter((node) => node.type === "file" && node.file_path)
      .map((node) => [node.file_path, node.id]),
  );
  chunkHits.forEach((chunkHit, index) => {
    if (isWikiNoiseFile(chunkHit.chunk.file_path)) {
      return;
    }
    const nodeId =
      chunkHit.chunk.node_id ?? fileNodesByPath.get(chunkHit.chunk.file_path);
    if (!nodeId || !nodeById.has(nodeId)) {
      return;
    }
    const node = nodeById.get(nodeId);
    if (!node || isWikiNoiseNode(node)) {
      return;
    }
    const score = Math.max(0.25, chunkHit.score - index * 0.01);
    const existing = seedHits.get(nodeId);
    if (existing) {
      existing.score = Math.max(existing.score, score);
      existing.reasons.add(chunkHit.match_type);
    } else {
      seedHits.set(nodeId, {
        nodeId,
        score,
        reasons: new Set([chunkHit.match_type]),
      });
    }
  });
}

function addOverviewFallbackSeeds(
  seedHits: Map<string, NodeHit>,
  nodes: CodeGraphNode[],
): void {
  const repository = nodes.find(
    (node) => node.type === "repository" && !isWikiNoiseNode(node),
  );
  if (repository) {
    seedHits.set(repository.id, {
      nodeId: repository.id,
      score: 0.4,
      reasons: new Set(["overview"]),
    });
  }
  for (const node of [...nodes].sort((left, right) =>
    left.file_path.localeCompare(right.file_path),
  )) {
    if (seedHits.size >= 6) {
      break;
    }
    if (!isWikiNoiseNode(node) && node.type === "file") {
      seedHits.set(node.id, {
        nodeId: node.id,
        score: 0.35,
        reasons: new Set(["overview"]),
      });
    }
  }
}

function expand(
  seedHits: Map<string, NodeHit>,
  edges: CodeGraphEdge[],
  maxHops: number,
): {
  selectedIds: Set<string>;
  hops: Map<string, number>;
  scores: Map<string, number>;
} {
  const adjacency = new Map<string, CodeGraphEdge[]>();
  for (const edge of edges) {
    adjacency.set(edge.source_id, [
      ...(adjacency.get(edge.source_id) ?? []),
      edge,
    ]);
    adjacency.set(edge.target_id, [
      ...(adjacency.get(edge.target_id) ?? []),
      edge,
    ]);
  }

  const selectedIds = new Set(seedHits.keys());
  const hops = new Map([...seedHits.keys()].map((nodeId) => [nodeId, 0]));
  const scores = new Map(
    [...seedHits.entries()].map(([nodeId, hit]) => [nodeId, hit.score]),
  );
  let frontier = new Set(seedHits.keys());
  for (let hop = 1; hop <= maxHops; hop += 1) {
    const candidates = new Map<
      string,
      { score: number; edge: CodeGraphEdge }
    >();
    for (const nodeId of frontier) {
      for (const edge of adjacency.get(nodeId) ?? []) {
        const neighborId =
          edge.source_id === nodeId ? edge.target_id : edge.source_id;
        if (selectedIds.has(neighborId)) {
          continue;
        }
        const edgeWeight = (EDGE_WEIGHTS[edge.type] ?? 0.35) * edge.confidence;
        const score = (scores.get(nodeId) ?? 0.1) * edgeWeight * 0.78 ** hop;
        const current = candidates.get(neighborId);
        if (!current || score > current.score) {
          candidates.set(neighborId, { score, edge });
        }
      }
    }
    if (!candidates.size) {
      break;
    }
    const nextFrontier = new Set<string>();
    for (const [nodeId, candidate] of [...candidates.entries()].sort(
      (left, right) => right[1].score - left[1].score,
    )) {
      if (selectedIds.size >= MAX_EXPANDED_NODES) {
        break;
      }
      selectedIds.add(nodeId);
      hops.set(nodeId, hop);
      scores.set(nodeId, candidate.score);
      nextFrontier.add(nodeId);
    }
    frontier = nextFrontier;
    if (selectedIds.size >= MAX_EXPANDED_NODES) {
      break;
    }
  }
  return { selectedIds, hops, scores };
}

function relatedEdges(
  edges: CodeGraphEdge[],
  selectedIds: Set<string>,
): CodeGraphEdge[] {
  return edges
    .filter(
      (edge) =>
        selectedIds.has(edge.source_id) && selectedIds.has(edge.target_id),
    )
    .sort(
      (left, right) =>
        -(EDGE_WEIGHTS[left.type] ?? 0.35) +
          (EDGE_WEIGHTS[right.type] ?? 0.35) ||
        Number(left.is_inferred) - Number(right.is_inferred) ||
        left.type.localeCompare(right.type) ||
        left.source_id.localeCompare(right.source_id) ||
        left.target_id.localeCompare(right.target_id),
    )
    .slice(0, MAX_RELATED_EDGES);
}

function selectSourceChunks(options: {
  chunks: CodeChunk[];
  chunkHits: CodeChunkHit[];
  nodes: CodeGraphNode[];
  edges: CodeGraphEdge[];
  selectedIds: Set<string>;
  seedIds: Set<string>;
  hops: Map<string, number>;
  maxSourceChunks: number;
  contextTokenBudget: number;
}): RankedChunkHit[] {
  const candidates = new Map<string, CodeChunk>();
  for (const hit of options.chunkHits) {
    candidates.set(hit.chunk.id, hit.chunk);
  }
  const fileNodeByPath = new Map(
    options.nodes
      .filter((node) => node.type === "file" && node.file_path)
      .map((node) => [node.file_path, node]),
  );
  for (const chunk of options.chunks) {
    const nodeId = chunkNodeId(chunk, options.nodes, fileNodeByPath);
    if (nodeId && options.selectedIds.has(nodeId)) {
      candidates.set(chunk.id, chunk);
    }
  }

  const ranked = rankSourceChunks([...candidates.values()], {
    nodes: options.nodes,
    edges: options.edges,
    seedIds: options.seedIds,
    hops: options.hops,
    chunkHits: options.chunkHits,
  });
  const packed: RankedChunkHit[] = [];
  let tokenTotal = 0;
  for (const hit of ranked) {
    if (packed.length >= options.maxSourceChunks) {
      break;
    }
    if (isWikiNoiseFile(hit.chunk.file_path)) {
      continue;
    }
    if (hit.chunk.token_count > options.contextTokenBudget) {
      continue;
    }
    if (tokenTotal + hit.chunk.token_count > options.contextTokenBudget) {
      continue;
    }
    packed.push(hit);
    tokenTotal += hit.chunk.token_count;
  }
  return packed;
}

function rankSourceChunks(
  chunks: CodeChunk[],
  options: {
    nodes: CodeGraphNode[];
    edges: CodeGraphEdge[];
    seedIds: Set<string>;
    hops: Map<string, number>;
    chunkHits: CodeChunkHit[];
  },
): RankedChunkHit[] {
  const nodeById = new Map(options.nodes.map((node) => [node.id, node]));
  const fileNodeByPath = new Map(
    options.nodes
      .filter((node) => node.type === "file" && node.file_path)
      .map((node) => [node.file_path, node]),
  );
  const hitScores = chunkHitScores(options.chunkHits);
  const centrality = degreeCentrality(options.nodes, options.edges);
  const freshness = freshnessScores(chunks, nodeById, fileNodeByPath);
  return chunks
    .map((chunk) => {
      const nodeId = chunkNodeId(chunk, options.nodes, fileNodeByPath);
      const semanticScore = hitScores.semantic.get(chunk.id) ?? 0;
      const keywordScore = hitScores.keyword.get(chunk.id) ?? 0;
      const graphScore = graphProximityScore(nodeId, options.hops);
      const centralityScore = centrality.get(nodeId ?? "") ?? 0;
      const freshnessScore = freshness.get(chunk.id) ?? 0;
      const scoreComponents = {
        semantic_score: semanticScore,
        keyword_score: keywordScore,
        graph_proximity_score: graphScore,
        node_importance_score: centralityScore,
        source_freshness_score: freshnessScore,
      };
      const score =
        HYBRID_RANKING_WEIGHTS.semantic * semanticScore +
        HYBRID_RANKING_WEIGHTS.keyword * keywordScore +
        HYBRID_RANKING_WEIGHTS.graph_proximity * graphScore +
        HYBRID_RANKING_WEIGHTS.node_importance * centralityScore +
        HYBRID_RANKING_WEIGHTS.source_freshness * freshnessScore;
      const reasons = rankingReasons({
        semanticScore,
        keywordScore,
        graphScore,
        nodeId,
        seedIds: options.seedIds,
      });
      return {
        chunk,
        score,
        reasons,
        scoreComponents,
        matchType: [...reasons].sort().join("+") || "hybrid_rank",
      };
    })
    .sort(
      (left, right) =>
        right.score - left.score ||
        left.chunk.file_path.localeCompare(right.chunk.file_path) ||
        left.chunk.start_line - right.chunk.start_line,
    );
}

async function communitySummaries(
  store: CodeWikiStoreApi,
  repoId: string,
  selectedIds: Set<string>,
): Promise<JsonObject[]> {
  const allCommunities = await store.listGraphCommunities(repoId);
  const byId = new Map(
    allCommunities.map((community) => [community.id, community]),
  );
  const parentIds = new Set(
    allCommunities
      .map((community) => community.parent_id)
      .filter((id): id is string => Boolean(id)),
  );
  const matched = allCommunities.flatMap((community) => {
    const overlap = community.node_ids
      .filter((nodeId) => selectedIds.has(nodeId))
      .sort();
    return overlap.length
      ? [communityRetrievalPayload(community, overlap)]
      : [];
  });
  const leaves = matched.filter(
    (community) => !parentIds.has(stringValue(community.id) ?? ""),
  );
  const parents = matched.filter(
    (community) =>
      parentIds.has(stringValue(community.id) ?? "") ||
      !stringValue(community.parent_id),
  );
  if (!leaves.length) {
    return matched
      .sort(
        (left, right) =>
          matchedNodeCount(right) - matchedNodeCount(left) ||
          numberValue(left.level) - numberValue(right.level) ||
          (stringValue(left.name) ?? "").localeCompare(
            stringValue(right.name) ?? "",
          ),
      )
      .slice(0, MAX_COMMUNITY_SUMMARIES);
  }

  const selectedLeaves: JsonObject[] = [];
  const siblingsByParent = new Map<string, number>();
  for (const child of [...leaves].sort(
    (left, right) =>
      matchedNodeCount(right) - matchedNodeCount(left) ||
      numberValue(right.level) - numberValue(left.level) ||
      (stringValue(left.name) ?? "").localeCompare(
        stringValue(right.name) ?? "",
      ),
  )) {
    const parentId = stringValue(child.parent_id) ?? "";
    if (
      (siblingsByParent.get(parentId) ?? 0) >= MAX_CHILDREN_PER_PARENT_IN_PROMPT
    ) {
      continue;
    }
    selectedLeaves.push(child);
    siblingsByParent.set(parentId, (siblingsByParent.get(parentId) ?? 0) + 1);
    if (selectedLeaves.length >= MAX_CHILD_SUMMARIES) {
      break;
    }
  }

  const selectedParentIds = ancestorIds(selectedLeaves, byId);
  const selectedParents = selectedParentIds.flatMap((parentId) => {
    const parent = byId.get(parentId);
    return parent
      ? [
          communityRetrievalPayload(
            parent,
            parent.node_ids.filter((nodeId) => selectedIds.has(nodeId)).sort(),
          ),
        ]
      : [];
  });
  if (selectedParents.length < MAX_PARENT_SUMMARIES) {
    for (const parentSummary of [...parents].sort(
      (left, right) =>
        matchedNodeCount(right) - matchedNodeCount(left) ||
        (stringValue(left.name) ?? "").localeCompare(
          stringValue(right.name) ?? "",
        ),
    )) {
      if (
        selectedParents.some(
          (parent) => stringValue(parent.id) === stringValue(parentSummary.id),
        )
      ) {
        continue;
      }
      selectedParents.push(parentSummary);
      if (selectedParents.length >= MAX_PARENT_SUMMARIES) {
        break;
      }
    }
  }
  return [
    ...selectedParents.slice(0, MAX_PARENT_SUMMARIES),
    ...selectedLeaves,
  ].slice(0, MAX_COMMUNITY_SUMMARIES);
}

function contextPackPayload(options: {
  query: string;
  chunks: RankedChunkHit[];
  relatedEdges: JsonObject[];
  nodes: JsonObject[];
  communities: JsonObject[];
  communityEdges: JsonObject[];
}): JsonObject {
  const parts = [`Query: ${options.query}`, "", "Source Chunks:"];
  for (const hit of options.chunks) {
    parts.push(
      `[${hit.chunk.id}] ${hit.chunk.file_path}:${hit.chunk.start_line}-${hit.chunk.end_line}`,
    );
    parts.push(hit.chunk.content.trimEnd());
    parts.push("");
  }
  if (options.communities.length) {
    parts.push("Community Summaries:");
    const parentIds = new Set(
      options.communities
        .filter((community) => numberValue(community.level) === 0)
        .map((community) => stringValue(community.id))
        .filter((id): id is string => Boolean(id)),
    );
    for (const community of options.communities.slice(
      0,
      MAX_COMMUNITY_SUMMARIES,
    )) {
      const level = numberValue(community.level);
      const label =
        level === 0
          ? "Architecture"
          : level === 1
            ? "Implementation"
            : "Detail";
      const indent =
        level > 0 && parentIds.has(stringValue(community.parent_id) ?? "")
          ? "  "
          : "";
      parts.push(
        `${indent}[${label}] ${stringValue(community.name) ?? ""} (${stringValue(community.id) ?? ""}): ${stringValue(community.summary) ?? ""}`,
      );
    }
    parts.push("");
  }
  if (options.communityEdges.length) {
    parts.push("Community Relationships:");
    for (const edge of options.communityEdges.slice(0, MAX_COMMUNITY_EDGES)) {
      parts.push(
        `- ${stringValue(edge.source) ?? ""} -[${stringValue(edge.type) ?? ""}]-> ${stringValue(edge.target) ?? ""}` +
          ` (confidence=${numberValue(edge.confidence)}, reason=${stringValue(edge.reason) ?? null})`,
      );
    }
    parts.push("");
  }
  parts.push("Graph Facts:");
  for (const edge of options.relatedEdges.slice(0, 40)) {
    parts.push(
      `- ${stringValue(edge.source) ?? ""} -[${stringValue(edge.type) ?? ""}]-> ${stringValue(edge.target) ?? ""}` +
        ` (confidence=${numberValue(edge.confidence)}, level=${stringValue(edge.confidence_level)}, reason=${stringValue(edge.reason)})`,
    );
  }
  const text = parts.join("\n").trim();
  return {
    text,
    token_count: estimateTokens(text),
    node_count: options.nodes.length,
    edge_count: options.relatedEdges.length,
    community_edge_count: options.communityEdges.length,
    chunk_count: options.chunks.length,
    community_count: options.communities.length,
    source_chunk_ids: options.chunks.map((hit) => hit.chunk.id),
    node_ids: options.nodes.map((node) => stringValue(node.id) ?? ""),
    edge_ids: options.relatedEdges.map((edge) => stringValue(edge.id) ?? ""),
    community_ids: options.communities.map(
      (community) => stringValue(community.id) ?? "",
    ),
    community_edge_ids: options.communityEdges.map(
      (edge) => stringValue(edge.id) ?? "",
    ),
  };
}

function traceId(
  repoId: string,
  query: string,
  seedNodeIds: string[],
  chunkIds: string[],
): string {
  const digest = createHash("sha1")
    .update([query, ...[...seedNodeIds].sort(), ...chunkIds].join("|"))
    .digest("hex")
    .slice(0, 24);
  return `${repoId}:trace:${digest}`;
}

function chunkHitScores(chunkHits: CodeChunkHit[]): {
  semantic: Map<string, number>;
  keyword: Map<string, number>;
} {
  const semantic = new Map<string, number>();
  const keyword = new Map<string, number>();
  for (const hit of chunkHits) {
    const target = hit.match_type.includes("vector") ? semantic : keyword;
    target.set(
      hit.chunk.id,
      Math.max(target.get(hit.chunk.id) ?? 0, clamp01(hit.score)),
    );
  }
  return { semantic, keyword };
}

function chunkNodeId(
  chunk: CodeChunk,
  nodes: CodeGraphNode[],
  fileNodeByPath: Map<string, CodeGraphNode>,
): string | null {
  if (chunk.node_id && nodes.some((node) => node.id === chunk.node_id)) {
    return chunk.node_id;
  }
  return fileNodeByPath.get(chunk.file_path)?.id ?? null;
}

function graphProximityScore(
  nodeId: string | null,
  hops: Map<string, number>,
): number {
  if (!nodeId || !hops.has(nodeId)) {
    return 0;
  }
  return 1 / ((hops.get(nodeId) ?? 0) + 1);
}

function degreeCentrality(
  nodes: CodeGraphNode[],
  edges: CodeGraphEdge[],
): Map<string, number> {
  const degrees = new Map(nodes.map((node) => [node.id, 0]));
  for (const edge of edges) {
    if (degrees.has(edge.source_id)) {
      degrees.set(edge.source_id, (degrees.get(edge.source_id) ?? 0) + 1);
    }
    if (degrees.has(edge.target_id)) {
      degrees.set(edge.target_id, (degrees.get(edge.target_id) ?? 0) + 1);
    }
  }
  const maxDegree = Math.max(0, ...degrees.values());
  return new Map(
    [...degrees.entries()].map(([nodeId, degree]) => [
      nodeId,
      maxDegree > 0 ? degree / maxDegree : 0,
    ]),
  );
}

function freshnessScores(
  chunks: CodeChunk[],
  nodeById: Map<string, CodeGraphNode>,
  fileNodeByPath: Map<string, CodeGraphNode>,
): Map<string, number> {
  const timestamps = new Map(
    chunks.map((chunk) => [
      chunk.id,
      chunkTimestamp(chunk, nodeById, fileNodeByPath),
    ]),
  );
  const present = [...timestamps.values()].filter(
    (value): value is number => typeof value === "number",
  );
  if (!present.length) {
    return new Map(chunks.map((chunk) => [chunk.id, 0]));
  }
  const min = Math.min(...present);
  const max = Math.max(...present);
  if (min === max) {
    return new Map(
      [...timestamps.entries()].map(([chunkId, timestamp]) => [
        chunkId,
        timestamp === null ? 0 : 1,
      ]),
    );
  }
  const span = max - min;
  return new Map(
    [...timestamps.entries()].map(([chunkId, timestamp]) => [
      chunkId,
      timestamp === null ? 0 : (timestamp - min) / span,
    ]),
  );
}

function chunkTimestamp(
  chunk: CodeChunk,
  nodeById: Map<string, CodeGraphNode>,
  fileNodeByPath: Map<string, CodeGraphNode>,
): number | null {
  const candidates = [
    chunk.node_id ? nodeById.get(chunk.node_id) : null,
    fileNodeByPath.get(chunk.file_path) ?? null,
  ].filter((node): node is CodeGraphNode => Boolean(node));
  for (const node of candidates) {
    const timestamp = metadataTimestamp(node.metadata);
    if (timestamp !== null) {
      return timestamp;
    }
  }
  return null;
}

function metadataTimestamp(metadata: JsonObject): number | null {
  for (const key of [
    "last_commit_at",
    "commit_time",
    "committed_at",
    "modified_at",
  ]) {
    const value = metadata[key];
    if (typeof value !== "string" || !value.trim()) {
      continue;
    }
    const timestamp = Date.parse(value.replace(/Z$/, "+00:00"));
    if (Number.isFinite(timestamp)) {
      return timestamp / 1000;
    }
  }
  return null;
}

function rankingReasons(options: {
  semanticScore: number;
  keywordScore: number;
  graphScore: number;
  nodeId: string | null;
  seedIds: Set<string>;
}): Set<string> {
  const reasons = new Set<string>();
  if (options.semanticScore > 0) {
    reasons.add("vector");
  }
  if (options.keywordScore > 0) {
    reasons.add("fts");
  }
  if (options.graphScore > 0) {
    reasons.add(
      options.nodeId && options.seedIds.has(options.nodeId)
        ? "seed_node"
        : "expanded_node",
    );
  }
  if (!reasons.size) {
    reasons.add("hybrid_rank");
  }
  return reasons;
}

function ancestorIds(
  communities: JsonObject[],
  byId: Map<string, GraphCommunity>,
): string[] {
  const ids: string[] = [];
  const seen = new Set<string>();
  for (const community of communities) {
    let parentId = stringValue(community.parent_id);
    while (parentId) {
      if (seen.has(parentId)) {
        break;
      }
      seen.add(parentId);
      ids.push(parentId);
      parentId = byId.get(parentId)?.parent_id ?? null;
    }
  }
  return ids;
}

function matchedNodeCount(community: JsonObject): number {
  return Array.isArray(community.matched_node_ids)
    ? community.matched_node_ids.length
    : 0;
}

function nodeHaystack(node: CodeGraphNode): string {
  const values = [
    node.name,
    node.type,
    node.file_path,
    node.symbol_id ?? "",
    node.language ?? "",
  ];
  for (const key of [
    "signature",
    "docstring",
    "route_method",
    "route_path",
    "handler",
  ]) {
    const value = node.metadata[key];
    if (typeof value === "string") {
      values.push(value);
    }
  }
  for (const key of ["fields", "bases", "decorators", "exports", "calls"]) {
    const value = node.metadata[key];
    if (Array.isArray(value)) {
      values.push(...value.map(String));
    }
  }
  return values.join(" ").toLowerCase();
}

function nodeTypeBoost(nodeType: string): number {
  return (
    {
      endpoint: 0.12,
      function: 0.1,
      method: 0.1,
      class: 0.08,
      schema: 0.08,
      file: 0.04,
      module: -0.1,
    }[nodeType] ?? 0
  );
}

function terms(value: string): string[] {
  return [...value.matchAll(TOKEN_RE)].map((match) => match[0].toLowerCase());
}

function estimateTokens(content: string): number {
  return Math.max(1, content.match(/\S+/g)?.length ?? 0);
}

function positiveInt(value: number | undefined, fallback: number): number {
  return typeof value === "number" && Number.isInteger(value) && value > 0
    ? value
    : fallback;
}

function boundedInt(
  value: number | undefined,
  fallback: number,
  min: number,
  max: number,
): number {
  const normalized =
    typeof value === "number" && Number.isInteger(value) ? value : fallback;
  return Math.max(min, Math.min(normalized, max));
}

function intersectionSize(left: Set<string>, right: Set<string>): number {
  let count = 0;
  for (const value of left) {
    if (right.has(value)) {
      count += 1;
    }
  }
  return count;
}

function clamp01(value: number): number {
  return Math.min(Math.max(value, 0), 1);
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function numberValue(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}
