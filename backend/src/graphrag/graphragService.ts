import type { CodeWikiStoreApi } from "../db/types.js";
import { notFoundError, validationError } from "../errors.js";
import type { LlmEmbeddingGateway } from "../llm/gateway.js";
import type { GraphRAGBuildResult, RetrievalTrace } from "../types.js";
import { EmbeddingIndex, type CodeChunkHit } from "./embeddingIndex.js";
import { buildRetrievalTrace, type RetrievalOptions } from "./retrieval.js";

export class GraphRAGService {
  constructor(
    private readonly store: CodeWikiStoreApi,
    private readonly embeddings?: LlmEmbeddingGateway,
  ) {}

  async buildIndex(
    repoId: string,
    options: { includeEmbeddings?: boolean } = {},
  ): Promise<GraphRAGBuildResult> {
    if (!this.store.getRepo(repoId)) {
      throw notFoundError("Repository", repoId);
    }
    const chunks = this.store.listCodeChunks(repoId);
    const embeddingResult =
      options.includeEmbeddings && this.embeddings
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
    if (!this.store.getRepo(repoId)) {
      throw notFoundError("Repository", repoId);
    }
    const normalizedQuery = query.trim();
    if (!normalizedQuery) {
      throw validationError("Retrieval query must be a non-empty string.");
    }

    const limit = positiveInt(options.limit, 10);
    const lexicalHits = this.store.searchCodeChunks(
      repoId,
      normalizedQuery,
      limit,
    );
    const vectorHits =
      options.includeEmbeddings && this.embeddings
        ? await this.embeddingIndex().search(
            repoId,
            normalizedQuery,
            this.store.listCodeChunks(repoId),
            limit,
          )
        : [];
    const chunkHits = mergeChunkHits(lexicalHits, vectorHits, limit);
    return this.store.saveRetrievalTrace(
      buildRetrievalTrace(this.store, repoId, normalizedQuery, {
        ...options,
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
