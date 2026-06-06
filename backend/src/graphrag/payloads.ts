import type {
  CodeChunk,
  CodeGraphEdge,
  CodeGraphNode,
  GraphCommunity,
  GraphCommunityEdge,
  JsonObject,
  JsonValue,
  RetrievalTrace,
} from "../types.js";

export function retrievalTracePayload(trace: RetrievalTrace): JsonObject {
  return {
    repo_id: trace.repo_id,
    query: trace.query,
    max_hops: trace.max_hops,
    trace_id: trace.trace_id,
    seed_nodes: trace.seed_nodes,
    expanded_nodes: trace.expanded_nodes,
    source_chunks: trace.source_chunks,
    related_edges: trace.related_edges,
    community_summaries: trace.community_summaries,
    community_edges: trace.community_edges,
    context_pack: trace.context_pack,
    chunks: trace.chunks,
    nodes: trace.nodes,
    edges: trace.edges,
    communities: trace.communities,
    context: trace.context,
    created_at: trace.created_at,
  };
}

export function nodeRetrievalPayload(
  node: CodeGraphNode,
  score: number,
  reasons: string[],
  hop: number,
): JsonObject {
  return {
    id: node.id,
    type: node.type,
    name: node.name,
    file_path: node.file_path,
    start_line: node.start_line,
    end_line: node.end_line,
    language: node.language,
    symbol_id: node.symbol_id,
    summary: node.summary,
    score: roundScore(score),
    reasons,
    hop,
    confidence: numberValue(node.metadata.confidence, 1),
    provenance: recordValue(node.metadata.provenance),
    metadata: node.metadata,
  };
}

export function edgeRetrievalPayload(edge: CodeGraphEdge): JsonObject {
  return {
    id: edge.id,
    source: edge.source_id,
    target: edge.target_id,
    source_id: edge.source_id,
    target_id: edge.target_id,
    type: edge.type,
    confidence: edge.confidence,
    confidence_level: stringValue(edge.metadata.confidence_level),
    reason: stringValue(edge.metadata.reason),
    weight: edge.weight,
    is_inferred: edge.is_inferred,
    provenance: recordValue(edge.metadata.provenance),
    metadata: edge.metadata,
  };
}

export function sourceChunkPayload(
  chunk: CodeChunk,
  score: number,
  matchType: string,
  index: number,
  options: {
    reasons?: string[];
    scoreComponents?: Record<string, number>;
  } = {},
): JsonObject {
  return {
    id: chunk.id,
    repo_id: chunk.repo_id,
    node_id: chunk.node_id,
    file_path: chunk.file_path,
    start_line: chunk.start_line,
    end_line: chunk.end_line,
    content: chunk.content,
    content_hash: chunk.content_hash,
    token_count: chunk.token_count,
    score: roundScore(score),
    score_components: scoreComponentsPayload(options.scoreComponents ?? {}),
    reasons: [...(options.reasons ?? [matchType])].sort(),
    match_type: matchType,
    citation_id: `S${index + 1}`,
  };
}

export function communityRetrievalPayload(
  community: GraphCommunity,
  matchedNodeIds: string[] = [],
): JsonObject {
  return {
    id: community.id,
    name: community.name,
    level: community.level,
    parent_id: community.parent_id,
    rank: community.rank,
    node_ids: community.node_ids,
    summary: community.summary ?? "",
    node_count: community.node_ids.length,
    matched_node_ids: matchedNodeIds,
  };
}

export function communityEdgeRetrievalPayload(
  edge: GraphCommunityEdge,
): JsonObject {
  return {
    id: edge.id,
    source: edge.source_community_id,
    target: edge.target_community_id,
    type: edge.type,
    weight: edge.weight,
    confidence: edge.confidence,
    reason: edge.reason,
    evidence_edge_ids: edge.evidence_edge_ids,
  };
}

function scoreComponentsPayload(
  components: Record<string, number>,
): JsonObject {
  return Object.fromEntries(
    Object.entries(components).map(([key, value]) => [key, roundScore(value)]),
  );
}

function roundScore(value: number): number {
  return Math.round(value * 10_000) / 10_000;
}

function numberValue(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function recordValue(value: unknown): JsonObject {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return {};
  }
  const result: JsonObject = {};
  for (const [key, nested] of Object.entries(value)) {
    if (isJsonValue(nested)) {
      result[key] = nested;
    }
  }
  return result;
}

function isJsonValue(value: unknown): value is JsonValue {
  if (
    value === null ||
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean"
  ) {
    return true;
  }
  if (Array.isArray(value)) {
    return value.every(isJsonValue);
  }
  return (
    typeof value === "object" &&
    value !== null &&
    Object.values(value).every(isJsonValue)
  );
}
