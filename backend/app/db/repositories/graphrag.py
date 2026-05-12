import json
import math

from backend.app.db.mappers import (
    code_chunk_embedding_from_row,
    code_chunk_from_row,
    graph_community_from_row,
)
from backend.app.db.records import (
    CodeChunkEmbeddingRecord,
    CodeChunkRecord,
    CodeChunkSearchHit,
    GraphCommunityRecord,
)


class GraphRAGRepositoryMixin:
    def replace_code_chunks(self, repo_id: str, chunks: list[CodeChunkRecord]) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM code_chunk_fts WHERE repo_id = ?", (repo_id,))
            connection.execute("DELETE FROM code_chunk WHERE repo_id = ?", (repo_id,))
            connection.executemany(
                """
                INSERT INTO code_chunk (
                  id, repo_id, node_id, file_path, start_line, end_line,
                  content, content_hash, token_count
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        chunk.id,
                        chunk.repo_id,
                        chunk.node_id,
                        chunk.file_path,
                        chunk.start_line,
                        chunk.end_line,
                        chunk.content,
                        chunk.content_hash,
                        chunk.token_count,
                    )
                    for chunk in chunks
                ],
            )
            connection.executemany(
                """
                INSERT INTO code_chunk_fts (
                  id, repo_id, node_id, file_path, start_line, end_line, content
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        chunk.id,
                        chunk.repo_id,
                        chunk.node_id,
                        chunk.file_path,
                        chunk.start_line,
                        chunk.end_line,
                        chunk.content,
                    )
                    for chunk in chunks
                ],
            )

    def replace_code_chunks_for_files(
        self,
        repo_id: str,
        file_paths: list[str],
        chunks: list[CodeChunkRecord],
    ) -> None:
        if not file_paths:
            return
        placeholders = ",".join("?" for _ in file_paths)
        params = (repo_id, *file_paths)
        with self.connect() as connection:
            connection.execute(
                f"DELETE FROM code_chunk_fts WHERE repo_id = ? AND file_path IN ({placeholders})",
                params,
            )
            connection.execute(
                f"DELETE FROM code_chunk WHERE repo_id = ? AND file_path IN ({placeholders})",
                params,
            )
            connection.executemany(
                """
                INSERT INTO code_chunk (
                  id, repo_id, node_id, file_path, start_line, end_line,
                  content, content_hash, token_count
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        chunk.id,
                        chunk.repo_id,
                        chunk.node_id,
                        chunk.file_path,
                        chunk.start_line,
                        chunk.end_line,
                        chunk.content,
                        chunk.content_hash,
                        chunk.token_count,
                    )
                    for chunk in chunks
                ],
            )
            connection.executemany(
                """
                INSERT INTO code_chunk_fts (
                  id, repo_id, node_id, file_path, start_line, end_line, content
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        chunk.id,
                        chunk.repo_id,
                        chunk.node_id,
                        chunk.file_path,
                        chunk.start_line,
                        chunk.end_line,
                        chunk.content,
                    )
                    for chunk in chunks
                ],
            )

    def list_code_chunks(self, repo_id: str) -> list[CodeChunkRecord]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, repo_id, node_id, file_path, start_line, end_line,
                       content, content_hash, token_count
                FROM code_chunk
                WHERE repo_id = ?
                ORDER BY file_path, start_line, end_line
                """,
                (repo_id,),
            ).fetchall()
        return [code_chunk_from_row(row) for row in rows]

    def get_code_chunks_by_node_ids(
        self,
        repo_id: str,
        node_ids: list[str],
    ) -> list[CodeChunkRecord]:
        if not node_ids:
            return []
        placeholders = ",".join("?" for _ in node_ids)
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT id, repo_id, node_id, file_path, start_line, end_line,
                       content, content_hash, token_count
                FROM code_chunk
                WHERE repo_id = ? AND node_id IN ({placeholders})
                ORDER BY file_path, start_line, end_line
                """,
                (repo_id, *node_ids),
            ).fetchall()
        return [code_chunk_from_row(row) for row in rows]

    def get_code_chunks_by_ids(self, repo_id: str, chunk_ids: list[str]) -> list[CodeChunkRecord]:
        if not chunk_ids:
            return []
        placeholders = ",".join("?" for _ in chunk_ids)
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT id, repo_id, node_id, file_path, start_line, end_line,
                       content, content_hash, token_count
                FROM code_chunk
                WHERE repo_id = ? AND id IN ({placeholders})
                ORDER BY file_path, start_line, end_line
                """,
                (repo_id, *chunk_ids),
            ).fetchall()
        return [code_chunk_from_row(row) for row in rows]

    def search_code_chunks_fts(
        self,
        repo_id: str,
        fts_query: str,
        *,
        limit: int = 20,
    ) -> list[CodeChunkSearchHit]:
        if not fts_query.strip():
            return []
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT c.id, c.repo_id, c.node_id, c.file_path, c.start_line, c.end_line,
                       c.content, c.content_hash, c.token_count,
                       bm25(code_chunk_fts) AS rank
                FROM code_chunk_fts
                JOIN code_chunk c ON c.id = code_chunk_fts.id
                WHERE code_chunk_fts MATCH ? AND code_chunk_fts.repo_id = ?
                ORDER BY rank
                LIMIT ?
                """,
                (fts_query, repo_id, limit),
            ).fetchall()
        return [
            CodeChunkSearchHit(
                chunk=code_chunk_from_row(row),
                score=max(0.1, 1.0 - index * 0.04),
                match_type="fts",
            )
            for index, row in enumerate(rows)
        ]

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

    def upsert_graph_community(self, community: GraphCommunityRecord) -> GraphCommunityRecord:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO graph_community (
                  id, repo_id, name, level, node_ids_json, summary, summary_hash
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  name = excluded.name,
                  level = excluded.level,
                  node_ids_json = excluded.node_ids_json,
                  summary = excluded.summary,
                  summary_hash = excluded.summary_hash
                """,
                (
                    community.id,
                    community.repo_id,
                    community.name,
                    community.level,
                    json.dumps(community.node_ids, sort_keys=True),
                    community.summary,
                    community.summary_hash,
                ),
            )
        return community

    def list_graph_communities(self, repo_id: str) -> list[GraphCommunityRecord]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, repo_id, name, level, node_ids_json, summary, summary_hash, created_at
                FROM graph_community
                WHERE repo_id = ?
                ORDER BY level, name
                """,
                (repo_id,),
            ).fetchall()
        return [graph_community_from_row(row) for row in rows]


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        return 0.0
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return sum(a * b for a, b in zip(left, right, strict=True)) / (left_norm * right_norm)
