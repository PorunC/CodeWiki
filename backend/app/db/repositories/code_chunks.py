from typing import Any

from sqlalchemy import delete, select, text

from backend.app.db.mappers import code_chunk_from_row
from backend.app.models import CodeChunkRecord, CodeChunkSearchHit

SQLITE_SAFE_BATCH_SIZE = 500


class CodeChunkRepositoryMixin:
    def replace_code_chunks(self, repo_id: str, chunks: list[CodeChunkRecord]) -> None:
        with self.orm_session() as session:
            session.execute(text("DELETE FROM code_chunk_fts WHERE repo_id = :repo_id"), {"repo_id": repo_id})
            session.execute(delete(CodeChunkRecord).where(CodeChunkRecord.repo_id == repo_id))
            session.commit()
            _insert_code_chunks(session, chunks)

    def sync_code_chunks(self, repo_id: str, chunks: list[CodeChunkRecord]) -> None:
        active_ids = {chunk.id for chunk in chunks}
        with self.orm_session() as session:
            existing_ids = set(
                session.scalars(select(CodeChunkRecord.id).where(CodeChunkRecord.repo_id == repo_id)).all()
            )
            stale_ids = existing_ids - active_ids
            new_chunks = [chunk for chunk in chunks if chunk.id not in existing_ids]

            if stale_ids:
                for stale_batch in _chunks(sorted(stale_ids), SQLITE_SAFE_BATCH_SIZE):
                    _delete_code_chunk_fts_by_ids(session, repo_id, stale_batch)
                    session.execute(
                        delete(CodeChunkRecord).where(
                            CodeChunkRecord.repo_id == repo_id,
                            CodeChunkRecord.id.in_(stale_batch),
                        )
                    )
                    session.commit()
            _insert_code_chunks(session, new_chunks)

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
            session.commit()
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
    if not chunks:
        return
    chunk_statement = text(
        """
            INSERT OR IGNORE INTO code_chunk (
              id, repo_id, node_id, file_path, start_line, end_line,
              content, content_hash, token_count
            )
            VALUES (
              :id, :repo_id, :node_id, :file_path, :start_line, :end_line,
              :content, :content_hash, :token_count
            )
        """
    )
    fts_statement = text(
        """
            INSERT OR IGNORE INTO code_chunk_fts (
              id, repo_id, node_id, file_path, start_line, end_line, content
            )
            VALUES (
              :id, :repo_id, :node_id, :file_path, :start_line, :end_line, :content
            )
        """
    )
    for batch in _chunks(chunks, SQLITE_SAFE_BATCH_SIZE):
        mappings = [_chunk_mapping(chunk) for chunk in batch]
        session.execute(chunk_statement, mappings)
        session.execute(fts_statement, mappings)
        session.commit()


def _delete_code_chunk_fts_by_ids(session, repo_id: str, chunk_ids: list[str]) -> None:
    if not chunk_ids:
        return
    params = {f"id_{index}": chunk_id for index, chunk_id in enumerate(chunk_ids)}
    placeholders = ",".join(f":{key}" for key in params)
    session.execute(
        text(f"DELETE FROM code_chunk_fts WHERE repo_id = :repo_id AND id IN ({placeholders})"),
        {"repo_id": repo_id, **params},
    )


def _chunks[T](items: list[T], size: int) -> list[list[T]]:
    return [items[index:index + size] for index in range(0, len(items), size)]


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
