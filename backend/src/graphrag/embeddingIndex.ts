import { digest } from "../analysis/graphUtils.js";
import type { CodeWikiStoreApi } from "../db/types.js";
import { validationError } from "../errors.js";
import { providerUserIdForRepo } from "../llm/cache.js";
import type { LlmEmbeddingGateway } from "../llm/gateway.js";
import type { CodeChunk, CodeChunkEmbedding } from "../types.js";

export type EmbeddingIndexBuildResult = {
  count: number;
  model: string;
};

export type CodeChunkHit = {
  chunk: CodeChunk;
  score: number;
  match_type: string;
};

export class EmbeddingIndex {
  constructor(
    private readonly store: CodeWikiStoreApi,
    private readonly provider: LlmEmbeddingGateway,
    private readonly batchSize = 32,
  ) {}

  async build(
    repoId: string,
    chunks: CodeChunk[],
  ): Promise<EmbeddingIndexBuildResult> {
    const model = this.embeddingModel();
    const vectorsByHash = await this.vectorsByContentHash(repoId, model);
    const missingChunks = uniqueChunksByContentHash(chunks).filter(
      (chunk) => !vectorsByHash.has(chunk.content_hash),
    );

    for (const batch of batches(missingChunks, this.batchSize)) {
      const result = await this.provider.embed(
        "embedding",
        batch.map(embeddingText),
        { providerUserId: providerUserIdForRepo(repoId) },
      );
      if (result.embeddings.length !== batch.length) {
        throw validationError(
          `Embedding provider returned ${result.embeddings.length} vectors for ${batch.length} chunks.`,
        );
      }
      batch.forEach((chunk, index) => {
        vectorsByHash.set(chunk.content_hash, result.embeddings[index]!);
      });
    }

    const embeddings = chunks.flatMap((chunk) => {
      const vector = vectorsByHash.get(chunk.content_hash);
      return vector ? [embeddingRecord(repoId, model, chunk, vector)] : [];
    });
    this.store.replaceCodeChunkEmbeddings(repoId, { model, embeddings });
    return { count: embeddings.length, model };
  }

  async ensure(
    repoId: string,
    chunks: CodeChunk[],
  ): Promise<EmbeddingIndexBuildResult | null> {
    const model = this.embeddingModel();
    const existingChunkIds = new Set(
      this.store
        .listCodeChunkEmbeddings(repoId, { model })
        .map((embedding) => embedding.chunk_id),
    );
    if (
      chunks.length > 0 &&
      chunks.every((chunk) => existingChunkIds.has(chunk.id))
    ) {
      return null;
    }
    return this.build(repoId, chunks);
  }

  async search(
    repoId: string,
    query: string,
    chunks: CodeChunk[],
    limit: number,
  ): Promise<CodeChunkHit[]> {
    await this.ensure(repoId, chunks);
    const model = this.embeddingModel();
    const result = await this.provider.embed("embedding", [query], {
      providerUserId: providerUserIdForRepo(repoId),
    });
    const [queryEmbedding] = result.embeddings;
    if (!queryEmbedding) {
      return [];
    }
    return this.store.searchCodeChunkEmbeddings(repoId, {
      model,
      queryEmbedding,
      limit,
    });
  }

  private embeddingModel(): string {
    if (!this.provider.isConfigured("embedding")) {
      throw validationError(
        "Embedding search requires CODEWIKI_LLM__PROFILES__EMBEDDING__MODEL plus credentials or an endpoint.",
      );
    }
    return this.provider.profile("embedding").model;
  }

  private async vectorsByContentHash(
    repoId: string,
    model: string,
  ): Promise<Map<string, number[]>> {
    return new Map(
      this.store
        .listCodeChunkEmbeddings(repoId, { model })
        .filter((embedding) => embedding.embedding.length > 0)
        .map((embedding) => [embedding.content_hash, embedding.embedding]),
    );
  }
}

function embeddingRecord(
  repoId: string,
  model: string,
  chunk: CodeChunk,
  vector: number[],
): CodeChunkEmbedding {
  return {
    id: digest(
      [repoId, "embedding", model, chunk.id, chunk.content_hash].join("\0"),
    ),
    repo_id: repoId,
    chunk_id: chunk.id,
    model,
    dimensions: vector.length,
    embedding: vector,
    content_hash: chunk.content_hash,
    created_at: null,
  };
}

function embeddingText(chunk: CodeChunk): string {
  return [
    `File: ${chunk.file_path}`,
    `Lines: ${chunk.start_line}-${chunk.end_line}`,
    chunk.content,
  ].join("\n");
}

function uniqueChunksByContentHash(chunks: CodeChunk[]): CodeChunk[] {
  const seen = new Set<string>();
  const result: CodeChunk[] = [];
  for (const chunk of chunks) {
    if (seen.has(chunk.content_hash)) {
      continue;
    }
    seen.add(chunk.content_hash);
    result.push(chunk);
  }
  return result;
}

function batches<T>(items: T[], size: number): T[][] {
  const normalizedSize = Math.max(1, size);
  const result: T[][] = [];
  for (let index = 0; index < items.length; index += normalizedSize) {
    result.push(items.slice(index, index + normalizedSize));
  }
  return result;
}
