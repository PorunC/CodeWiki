import type { CodeWikiSqliteDatabase } from "./sqlite.js";
import type { CodeChunk, CodeChunkEmbedding } from "../types.js";
import {
  chunkFromRow,
  embeddingFromRow,
  stringifyJson,
  type Row,
} from "./mappers.js";

export type CodeChunkEmbeddingSearchOptions = {
  model: string;
  queryEmbedding: number[];
  limit?: number | undefined;
};

export class CodeChunkEmbeddingRepository {
  constructor(private readonly db: CodeWikiSqliteDatabase) {}

  replaceCodeChunkEmbeddings(
    repoId: string,
    options: { model: string; embeddings: CodeChunkEmbedding[] },
  ): void {
    const tx = this.db.transaction(() => {
      this.db
        .prepare(
          "DELETE FROM code_chunk_embedding WHERE repo_id = ? AND model = ?",
        )
        .run(repoId, options.model);
      const insert = this.db.prepare(
        `
        INSERT INTO code_chunk_embedding (
          id, repo_id, chunk_id, model, dimensions, embedding_json, content_hash, created_at
        )
        VALUES (
          @id, @repo_id, @chunk_id, @model, @dimensions, @embedding_json,
          @content_hash, @created_at
        )
        `,
      );
      for (const embedding of options.embeddings) {
        insert.run({
          ...embedding,
          embedding_json: stringifyJson(embedding.embedding),
        });
      }
    });
    tx();
  }

  listCodeChunkEmbeddings(
    repoId: string,
    options: { model?: string | undefined } = {},
  ): CodeChunkEmbedding[] {
    const rows = options.model
      ? (this.db
          .prepare(
            `
            SELECT * FROM code_chunk_embedding
            WHERE repo_id = ? AND model = ?
            ORDER BY created_at DESC, chunk_id
            `,
          )
          .all(repoId, options.model) as Row[])
      : (this.db
          .prepare(
            `
            SELECT * FROM code_chunk_embedding
            WHERE repo_id = ?
            ORDER BY created_at DESC, model, chunk_id
            `,
          )
          .all(repoId) as Row[]);
    return rows.map(embeddingFromRow);
  }

  searchCodeChunkEmbeddings(
    repoId: string,
    options: CodeChunkEmbeddingSearchOptions,
  ): Array<{ chunk: CodeChunk; score: number; match_type: string }> {
    const limit = positiveInt(options.limit, 20);
    const queryEmbedding = validVector(options.queryEmbedding);
    if (!queryEmbedding.length) {
      return [];
    }
    const chunkById = new Map(
      (
        this.db
          .prepare("SELECT * FROM code_chunk WHERE repo_id = ?")
          .all(repoId) as Row[]
      ).map((row) => {
        const chunk = chunkFromRow(row);
        return [chunk.id, chunk] as const;
      }),
    );
    return this.listCodeChunkEmbeddings(repoId, { model: options.model })
      .filter((embedding) => embedding.dimensions === queryEmbedding.length)
      .flatMap((embedding) => {
        const chunk = chunkById.get(embedding.chunk_id);
        if (!chunk) {
          return [];
        }
        const score = cosineSimilarity(queryEmbedding, embedding.embedding);
        return score > 0 ? [{ chunk, score, match_type: "vector" }] : [];
      })
      .sort(
        (left, right) =>
          right.score - left.score ||
          left.chunk.file_path.localeCompare(right.chunk.file_path) ||
          left.chunk.start_line - right.chunk.start_line,
      )
      .slice(0, limit);
  }
}

function cosineSimilarity(left: number[], right: number[]): number {
  if (left.length !== right.length || left.length === 0) {
    return 0;
  }
  let dot = 0;
  let leftNorm = 0;
  let rightNorm = 0;
  for (let index = 0; index < left.length; index += 1) {
    const leftValue = left[index] ?? 0;
    const rightValue = right[index] ?? 0;
    dot += leftValue * rightValue;
    leftNorm += leftValue * leftValue;
    rightNorm += rightValue * rightValue;
  }
  if (leftNorm === 0 || rightNorm === 0) {
    return 0;
  }
  return dot / (Math.sqrt(leftNorm) * Math.sqrt(rightNorm));
}

function validVector(values: number[]): number[] {
  return values.filter((value) => Number.isFinite(value));
}

function positiveInt(value: number | undefined, fallback: number): number {
  return typeof value === "number" && Number.isInteger(value) && value > 0
    ? value
    : fallback;
}
