import type {
  CodeChunk,
  CodeGraphEdge,
  CodeGraphNode,
  GraphCommunity,
  GraphCommunityEdge,
  JsonObject,
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
    score,
    reasons,
    hop,
    metadata: node.metadata,
  };
}

export function edgeRetrievalPayload(edge: CodeGraphEdge): JsonObject {
  return {
    id: edge.id,
    source: edge.source_id,
    target: edge.target_id,
    type: edge.type,
    confidence: edge.confidence,
    weight: edge.weight,
    is_inferred: edge.is_inferred,
    metadata: edge.metadata,
  };
}

export function sourceChunkPayload(
  chunk: CodeChunk,
  score: number,
  matchType: string,
  index: number,
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
    score,
    match_type: matchType,
    citation_id: `S${index + 1}`,
  };
}

export function communityRetrievalPayload(
  community: GraphCommunity,
): JsonObject {
  return {
    id: community.id,
    name: community.name,
    level: community.level,
    parent_id: community.parent_id,
    rank: community.rank,
    node_ids: community.node_ids,
    summary: community.summary ?? "",
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
