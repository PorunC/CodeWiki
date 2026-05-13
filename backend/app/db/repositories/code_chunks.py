from backend.app.db.mappers import code_chunk_from_row
from backend.app.db.records import CodeChunkRecord, CodeChunkSearchHit


class CodeChunkRepositoryMixin:
    def replace_code_chunks(self, repo_id: str, chunks: list[CodeChunkRecord]) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM code_chunk_fts WHERE repo_id = ?", (repo_id,))
            connection.execute("DELETE FROM code_chunk WHERE repo_id = ?", (repo_id,))
            _insert_code_chunks(connection, chunks)

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
            _insert_code_chunks(connection, chunks)

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


def _insert_code_chunks(connection, chunks: list[CodeChunkRecord]) -> None:
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
