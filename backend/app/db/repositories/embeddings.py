import json
import math

from backend.app.db.mappers import code_chunk_embedding_from_row
from backend.app.db.records import CodeChunkEmbeddingRecord, CodeChunkSearchHit


class CodeChunkEmbeddingRepositoryMixin:
    def replace_code_chunk_embeddings(
        self,
        repo_id: str,
        *,
        model: str,
        embeddings: list[CodeChunkEmbeddingRecord],
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                "DELETE FROM code_chunk_embedding WHERE repo_id = ? AND model = ?",
                (repo_id, model),
            )
            connection.executemany(
                """
                INSERT INTO code_chunk_embedding (
                  id, repo_id, chunk_id, model, dimensions, embedding_json, content_hash
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        embedding.id,
                        embedding.repo_id,
                        embedding.chunk_id,
                        embedding.model,
                        embedding.dimensions,
                        json.dumps(embedding.embedding),
                        embedding.content_hash,
                    )
                    for embedding in embeddings
                ],
            )

    def list_code_chunk_embeddings(
        self,
        repo_id: str,
        *,
        model: str | None = None,
    ) -> list[CodeChunkEmbeddingRecord]:
        params: tuple[str, ...]
        where = "repo_id = ?"
        params = (repo_id,)
        if model is not None:
            where += " AND model = ?"
            params = (repo_id, model)
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT id, repo_id, chunk_id, model, dimensions,
                       embedding_json, content_hash, created_at
                FROM code_chunk_embedding
                WHERE {where}
                ORDER BY created_at DESC, chunk_id
                """,
                params,
            ).fetchall()
        return [code_chunk_embedding_from_row(row) for row in rows]

    def search_code_chunk_embeddings(
        self,
        repo_id: str,
        *,
        model: str,
        query_embedding: list[float],
        limit: int = 20,
    ) -> list[CodeChunkSearchHit]:
        if not query_embedding:
            return []
        embeddings = self.list_code_chunk_embeddings(repo_id, model=model)
        chunk_ids = [embedding.chunk_id for embedding in embeddings]
        chunks = {chunk.id: chunk for chunk in self.get_code_chunks_by_ids(repo_id, chunk_ids)}
        hits: list[CodeChunkSearchHit] = []
        for embedding in embeddings:
            chunk = chunks.get(embedding.chunk_id)
            if chunk is None:
                continue
            score = _cosine_similarity(query_embedding, embedding.embedding)
            if score <= 0:
                continue
            hits.append(CodeChunkSearchHit(chunk=chunk, score=score, match_type="vector"))
        return sorted(hits, key=lambda hit: hit.score, reverse=True)[:limit]


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        return 0.0
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return sum(a * b for a, b in zip(left, right, strict=True)) / (left_norm * right_norm)
