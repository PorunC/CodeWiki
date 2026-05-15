from typing import Any

from sqlalchemy import delete, select, text

from backend.app.db.mappers import code_chunk_from_row
from backend.app.models import CodeChunkRecord, CodeChunkSearchHit


class CodeChunkRepositoryMixin:
    def replace_code_chunks(self, repo_id: str, chunks: list[CodeChunkRecord]) -> None:
        with self.orm_session() as session:
            session.execute(text("DELETE FROM code_chunk_fts WHERE repo_id = :repo_id"), {"repo_id": repo_id})
            session.execute(delete(CodeChunkRecord).where(CodeChunkRecord.repo_id == repo_id))
            _insert_code_chunks(session, chunks)

    def replace_code_chunks_for_files(
        self,
        repo_id: str,
        file_paths: list[str],
        chunks: list[CodeChunkRecord],
    ) -> None:
        if not file_paths:
            return
        path_params = {f"path_{index}": path for index, path in enumerate(file_paths)}
        placeholders = ",".join(f":{key}" for key in path_params)
        with self.orm_session() as session:
            session.execute(
                text(f"DELETE FROM code_chunk_fts WHERE repo_id = :repo_id AND file_path IN ({placeholders})"),
                {"repo_id": repo_id, **path_params},
            )
            session.execute(
                delete(CodeChunkRecord).where(
                    CodeChunkRecord.repo_id == repo_id,
                    CodeChunkRecord.file_path.in_(file_paths),
                )
            )
            _insert_code_chunks(session, chunks)

    def list_code_chunks(self, repo_id: str) -> list[CodeChunkRecord]:
        with self.orm_session() as session:
            return list(
                session.scalars(
                    select(CodeChunkRecord)
                    .where(CodeChunkRecord.repo_id == repo_id)
                    .order_by(CodeChunkRecord.file_path, CodeChunkRecord.start_line, CodeChunkRecord.end_line)
                )
            )

    def get_code_chunks_by_node_ids(
        self,
        repo_id: str,
        node_ids: list[str],
    ) -> list[CodeChunkRecord]:
        if not node_ids:
            return []
        with self.orm_session() as session:
            return list(
                session.scalars(
                    select(CodeChunkRecord)
                    .where(CodeChunkRecord.repo_id == repo_id, CodeChunkRecord.node_id.in_(node_ids))
                    .order_by(CodeChunkRecord.file_path, CodeChunkRecord.start_line, CodeChunkRecord.end_line)
                )
            )

    def get_code_chunks_by_ids(self, repo_id: str, chunk_ids: list[str]) -> list[CodeChunkRecord]:
        if not chunk_ids:
            return []
        with self.orm_session() as session:
            return list(
                session.scalars(
                    select(CodeChunkRecord)
                    .where(CodeChunkRecord.repo_id == repo_id, CodeChunkRecord.id.in_(chunk_ids))
                    .order_by(CodeChunkRecord.file_path, CodeChunkRecord.start_line, CodeChunkRecord.end_line)
                )
            )

    def search_code_chunks_fts(
        self,
        repo_id: str,
        fts_query: str,
        *,
        limit: int = 20,
    ) -> list[CodeChunkSearchHit]:
        if not fts_query.strip():
            return []
        with self.orm_session() as session:
            rows = session.execute(
                text(
                    """
                SELECT c.id, c.repo_id, c.node_id, c.file_path, c.start_line, c.end_line,
                       c.content, c.content_hash, c.token_count,
                       bm25(code_chunk_fts) AS rank
                FROM code_chunk_fts
                JOIN code_chunk c ON c.id = code_chunk_fts.id
                WHERE code_chunk_fts MATCH :fts_query AND code_chunk_fts.repo_id = :repo_id
                ORDER BY rank
                LIMIT :limit
                """,
                ),
                {"fts_query": fts_query, "repo_id": repo_id, "limit": limit},
            ).mappings().all()
        return [
            CodeChunkSearchHit(
                chunk=code_chunk_from_row(row),
                score=max(0.1, 1.0 - index * 0.04),
                match_type="fts",
            )
            for index, row in enumerate(rows)
        ]


def _insert_code_chunks(session, chunks: list[CodeChunkRecord]) -> None:
    session.add_all(_clone_chunk(chunk) for chunk in chunks)
    if chunks:
        session.execute(
            text(
                """
            INSERT INTO code_chunk_fts (
              id, repo_id, node_id, file_path, start_line, end_line, content
            )
            VALUES (
              :id, :repo_id, :node_id, :file_path, :start_line, :end_line, :content
            )
            """
            ),
            [_chunk_mapping(chunk) for chunk in chunks],
        )


def _clone_chunk(chunk: CodeChunkRecord) -> CodeChunkRecord:
    return CodeChunkRecord(**chunk.as_record_dict())


def _chunk_mapping(chunk: CodeChunkRecord) -> dict[str, Any]:
    return {
        "id": chunk.id,
        "repo_id": chunk.repo_id,
        "node_id": chunk.node_id,
        "file_path": chunk.file_path,
        "start_line": chunk.start_line,
        "end_line": chunk.end_line,
        "content": chunk.content,
        "content_hash": chunk.content_hash,
        "token_count": chunk.token_count,
    }
