import type { CodeWikiStoreApi } from "../db/types.js";
import { notFoundError, validationError } from "../errors.js";
import type { LlmEmbeddingGateway } from "../llm/gateway.js";
import type {
  CodeChunk,
  CodeGraphNode,
  GraphRAGBuildResult,
  RetrievalTrace,
} from "../types.js";
import { buildSourceChunks } from "./chunkBuilder.js";
import {
  type GraphRagRetrievalDefaults,
  normalizeGraphRagRetrievalDefaults,
} from "./defaults.js";
import { EmbeddingIndex, type CodeChunkHit } from "./embeddingIndex.js";
import { buildRetrievalTrace, type RetrievalOptions } from "./retrieval.js";

export class GraphRAGService {
  private readonly retrievalDefaults: GraphRagRetrievalDefaults;

  constructor(
    private readonly store: CodeWikiStoreApi,
    private readonly embeddings?: LlmEmbeddingGateway,
    defaults: Partial<GraphRagRetrievalDefaults> = {},
  ) {
    this.retrievalDefaults = normalizeGraphRagRetrievalDefaults(defaults);
  }

  async buildIndex(
    repoId: string,
    options: { includeEmbeddings?: boolean } = {},
  ): Promise<GraphRAGBuildResult> {
    const repo = await this.store.getRepo(repoId);
    if (!repo) {
      throw notFoundError("Repository", repoId);
    }
    const graph = await this.store.getGraph(repoId);
    if (!graph.nodes.length) {
      return {
        repo_id: repoId,
        status: "empty_graph",
        chunk_count: 0,
        embedding_count: 0,
        embedding_model: null,
        include_embeddings: Boolean(options.includeEmbeddings),
      };
    }
    const chunks = await this.buildAndStoreSourceChunks(
      repoId,
      repo.path,
      graph.nodes,
    );
    const embeddingResult =
      options.includeEmbeddings && this.embeddings && chunks.length
        ? await this.embeddingIndex().build(repoId, chunks)
        : null;
    return {
      repo_id: repoId,
      status: "built",
      chunk_count: chunks.length,
      embedding_count: embeddingResult?.count ?? 0,
      embedding_model: embeddingResult?.model ?? null,
      include_embeddings: Boolean(options.includeEmbeddings),
    };
  }

  async retrieve(
    repoId: string,
    query: string,
    options: RetrievalOptions = {},
  ): Promise<RetrievalTrace> {
    const repo = await this.store.getRepo(repoId);
    if (!repo) {
      throw notFoundError("Repository", repoId);
    }
    const normalizedQuery = query.trim() || "repository overview";

    const limit = positiveInt(
      options.limit,
      this.retrievalDefaults.maxSourceChunks,
    );
    const graph = await this.store.getGraph(repoId);
    if (!graph.nodes.length) {
      throw validationError("Run analysis before GraphRAG retrieval.");
    }
    let chunks = await this.store.listCodeChunks(repoId);
    if (!chunks.length) {
      chunks = await this.buildAndStoreSourceChunks(
        repoId,
        repo.path,
        graph.nodes,
      );
    }
    const lexicalHits = await this.store.searchCodeChunks(
      repoId,
      normalizedQuery,
      limit,
    );
    const vectorHits =
      options.includeEmbeddings && this.embeddings
        ? await this.embeddingIndex().search(
            repoId,
            normalizedQuery,
            chunks,
            limit,
          )
        : [];
    const chunkHits = mergeChunkHits(lexicalHits, vectorHits, limit);
    return this.store.saveRetrievalTrace(
      await buildRetrievalTrace(this.store, repoId, normalizedQuery, {
        ...options,
        limit,
        contextTokenBudget:
          options.contextTokenBudget ??
          this.retrievalDefaults.contextTokenBudget,
        chunkHits,
      }),
    );
  }

  private embeddingIndex(): EmbeddingIndex {
    if (!this.embeddings) {
      throw validationError(
        "Embedding search requires an embedding-capable LLM provider.",
      );
    }
    return new EmbeddingIndex(this.store, this.embeddings);
  }

  private async buildAndStoreSourceChunks(
    repoId: string,
    repoPath: string,
    nodes: CodeGraphNode[],
  ): Promise<CodeChunk[]> {
    const chunks = buildSourceChunks(repoId, repoPath, nodes);
    await this.store.replaceCodeChunks(repoId, chunks);
    return chunks;
  }
}

function mergeChunkHits(
  lexicalHits: CodeChunkHit[],
  vectorHits: CodeChunkHit[],
  limit: number,
): CodeChunkHit[] {
  const byChunkId = new Map<string, CodeChunkHit>();
  for (const hit of [...lexicalHits, ...vectorHits]) {
    const existing = byChunkId.get(hit.chunk.id);
    if (!existing || hit.score > existing.score) {
      byChunkId.set(hit.chunk.id, hit);
      continue;
    }
    if (existing.match_type !== hit.match_type) {
      byChunkId.set(hit.chunk.id, {
        ...existing,
        match_type: `${existing.match_type}+${hit.match_type}`,
      });
    }
  }
  return [...byChunkId.values()]
    .sort(
      (left, right) =>
        right.score - left.score ||
        left.chunk.file_path.localeCompare(right.chunk.file_path) ||
        left.chunk.start_line - right.chunk.start_line,
    )
    .slice(0, limit);
}

function positiveInt(value: number | undefined, fallback: number): number {
  return typeof value === "number" && Number.isInteger(value) && value > 0
    ? value
    : fallback;
}
