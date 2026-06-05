import { createHash } from "node:crypto";
import type { CodeWikiStoreApi } from "../db/types.js";
import type { CodeChunk, RetrievalTrace } from "../types.js";
import type { CodeChunkHit } from "./embeddingIndex.js";
import {
  communityEdgeRetrievalPayload,
  communityRetrievalPayload,
  edgeRetrievalPayload,
  nodeRetrievalPayload,
  sourceChunkPayload,
} from "./payloads.js";

export type RetrievalOptions = {
  maxHops?: number;
  limit?: number;
  includeEmbeddings?: boolean;
  chunkHits?: CodeChunkHit[];
};

export async function buildRetrievalTrace(
  store: CodeWikiStoreApi,
  repoId: string,
  query: string,
  options: RetrievalOptions = {},
): Promise<RetrievalTrace> {
  const limit = positiveInt(options.limit, 10);
  const maxHops = positiveInt(options.maxHops, 2);
  const chunkHits =
    options.chunkHits ?? (await store.searchCodeChunks(repoId, query, limit));
  const nodeHits = await store.searchCodeNodes(repoId, query, { limit: 10 });
  const graph = await store.getGraph(repoId);

  const selectedNodeIds = new Set(nodeHits.map((hit) => hit.node.id));
  for (const hit of chunkHits) {
    if (hit.chunk.node_id) {
      selectedNodeIds.add(hit.chunk.node_id);
    }
  }

  const relatedEdges = graph.edges.filter(
    (edge) =>
      selectedNodeIds.has(edge.source_id) ||
      selectedNodeIds.has(edge.target_id),
  );
  for (const edge of relatedEdges) {
    selectedNodeIds.add(edge.source_id);
    selectedNodeIds.add(edge.target_id);
  }

  const selectedNodes = graph.nodes.filter((node) =>
    selectedNodeIds.has(node.id),
  );
  const selectedCommunities = (await store.listGraphCommunities(repoId)).filter(
    (community) =>
      community.node_ids.some((nodeId) => selectedNodeIds.has(nodeId)),
  );
  const selectedCommunityIds = new Set(
    selectedCommunities.map((community) => community.id),
  );
  const communityEdges = (await store.listGraphCommunityEdges(repoId)).filter(
    (edge) =>
      selectedCommunityIds.has(edge.source_community_id) ||
      selectedCommunityIds.has(edge.target_community_id),
  );

  const sourceChunks = chunkHits.map((hit, index) =>
    sourceChunkPayload(hit.chunk, hit.score, hit.match_type, index),
  );
  const seedNodes = nodeHits.map((hit) =>
    nodeRetrievalPayload(hit.node, hit.score, hit.reasons, 0),
  );
  const seedIds = new Set(nodeHits.map((hit) => hit.node.id));
  const expandedNodes = selectedNodes
    .filter((node) => !seedIds.has(node.id))
    .map((node) => nodeRetrievalPayload(node, 0.1, ["graph_expansion"], 1));
  const edgePayloads = relatedEdges.map(edgeRetrievalPayload);
  const communityPayloads = selectedCommunities.map(communityRetrievalPayload);
  const communityEdgePayloads = communityEdges.map(
    communityEdgeRetrievalPayload,
  );
  const context = chunkHits.map((hit) => hit.chunk.content).join("\n\n");
  const nodes = [...seedNodes, ...expandedNodes];

  return {
    repo_id: repoId,
    query,
    max_hops: maxHops,
    trace_id: traceId(
      repoId,
      query,
      nodeHits.map((hit) => hit.node.id),
      chunkHits.map((hit) => hit.chunk),
    ),
    seed_nodes: seedNodes,
    expanded_nodes: expandedNodes,
    source_chunks: sourceChunks,
    related_edges: edgePayloads,
    community_summaries: communityPayloads,
    community_edges: communityEdgePayloads,
    context_pack: {
      query,
      source_chunks: sourceChunks,
      related_edges: edgePayloads,
      nodes,
      communities: communityPayloads,
      community_edges: communityEdgePayloads,
      context,
      include_embeddings: Boolean(options.includeEmbeddings),
    },
    chunks: chunkHits.map((hit) => hit.chunk),
    nodes,
    edges: edgePayloads,
    communities: communityPayloads,
    context,
    created_at: null,
  };
}

function traceId(
  repoId: string,
  query: string,
  seedNodeIds: string[],
  chunks: CodeChunk[],
): string {
  const digest = createHash("sha1");
  digest.update(repoId);
  digest.update("\0trace\0");
  digest.update(query);
  for (const nodeId of [...seedNodeIds].sort()) {
    digest.update("\0");
    digest.update(nodeId);
  }
  for (const chunk of chunks) {
    digest.update("\0");
    digest.update(chunk.id);
  }
  return digest.digest("hex").slice(0, 24);
}

function positiveInt(value: number | undefined, fallback: number): number {
  return typeof value === "number" && Number.isInteger(value) && value > 0
    ? value
    : fallback;
}
