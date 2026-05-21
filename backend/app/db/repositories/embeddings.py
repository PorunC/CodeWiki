import struct

from sqlalchemy import delete, select, text

from backend.app.models import CodeChunkEmbeddingRecord, CodeChunkSearchHit


class CodeChunkEmbeddingRepositoryMixin:
    def replace_code_chunk_embeddings(
        self,
        repo_id: str,
        *,
        model: str,
        embeddings: list[CodeChunkEmbeddingRecord],
    ) -> None:
        with self.orm_session() as session:
            _delete_existing_vectors(session, repo_id, model)
            session.execute(
                delete(CodeChunkEmbeddingRecord).where(
                    CodeChunkEmbeddingRecord.repo_id == repo_id,
                    CodeChunkEmbeddingRecord.model == model,
                )
            )
            for embedding in embeddings:
                _insert_embedding(session, embedding)

    def sync_code_chunk_embeddings(
        self,
        repo_id: str,
        *,
        model: str,
        embeddings: list[CodeChunkEmbeddingRecord],
    ) -> None:
        active_by_chunk_id = {embedding.chunk_id: embedding for embedding in embeddings}
        with self.orm_session() as session:
            existing_rows = session.scalars(
                select(CodeChunkEmbeddingRecord).where(
                    CodeChunkEmbeddingRecord.repo_id == repo_id,
                    CodeChunkEmbeddingRecord.model == model,
                )
            ).all()
            stale_rows: list[CodeChunkEmbeddingRecord] = []
            changed_rows: list[CodeChunkEmbeddingRecord] = []
            kept_chunk_ids: set[str] = set()
            for row in existing_rows:
                active = active_by_chunk_id.get(row.chunk_id)
                if active is None:
                    stale_rows.append(row)
                elif _embedding_row_matches(session, row, active):
                    kept_chunk_ids.add(row.chunk_id)
                else:
                    changed_rows.append(row)

            rows_to_delete = [*stale_rows, *changed_rows]
            _delete_vector_rows(session, rows_to_delete)
            if rows_to_delete:
                session.execute(
                    delete(CodeChunkEmbeddingRecord).where(
                        CodeChunkEmbeddingRecord.id.in_([row.id for row in rows_to_delete]),
                    )
                )

            for embedding in embeddings:
                if embedding.chunk_id not in kept_chunk_ids:
                    _insert_embedding(session, embedding)

    def list_code_chunk_embeddings(
        self,
        repo_id: str,
        *,
        model: str | None = None,
    ) -> list[CodeChunkEmbeddingRecord]:
        with self.orm_session() as session:
            query = select(CodeChunkEmbeddingRecord).where(CodeChunkEmbeddingRecord.repo_id == repo_id)
            if model is not None:
                query = query.where(CodeChunkEmbeddingRecord.model == model)
            rows = session.scalars(
                query.order_by(CodeChunkEmbeddingRecord.created_at.desc(), CodeChunkEmbeddingRecord.chunk_id)
            ).all()
            for row in rows:
                row.embedding = _load_vector(session, row.vec_table, row.vec_rowid)
            return list(rows)

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
        dimensions = len(query_embedding)
        vec_table = _vec_table_name(dimensions)
        with self.orm_session() as session:
            if not _table_exists(session, vec_table):
                return []
            rows = session.execute(
                text(
                    f"""
                SELECT chunk_id, distance
                FROM {vec_table}
                WHERE embedding MATCH :embedding
                  AND repo_id = :repo_id
                  AND model = :model
                  AND k = :limit
                ORDER BY distance
                """
                ),
                {
                    "embedding": _serialize_float32(query_embedding),
                    "repo_id": repo_id,
                    "model": model,
                    "limit": limit,
                },
            ).mappings().all()

        chunk_ids = [row["chunk_id"] for row in rows]
        chunks = {chunk.id: chunk for chunk in self.get_code_chunks_by_ids(repo_id, chunk_ids)}
        hits: list[CodeChunkSearchHit] = []
        for row in rows:
            chunk = chunks.get(row["chunk_id"])
            if chunk is None:
                continue
            score = max(0.0, 1.0 - float(row["distance"]))
            if score <= 0:
                continue
            hits.append(CodeChunkSearchHit(chunk=chunk, score=score, match_type="vector"))
        return hits[:limit]


def _insert_embedding(session, embedding: CodeChunkEmbeddingRecord) -> None:
    if embedding.dimensions <= 0 or len(embedding.embedding) != embedding.dimensions:
        raise ValueError(f"Invalid embedding dimensions for chunk {embedding.chunk_id}")

    vec_table = _vec_table_name(embedding.dimensions)
    _ensure_vec_table(session, embedding.dimensions)
    cursor = session.execute(
        text(
            f"""
        INSERT INTO {vec_table} (embedding, repo_id, model, chunk_id)
        VALUES (:embedding, :repo_id, :model, :chunk_id)
        """
        ),
        {
            "embedding": _serialize_float32(embedding.embedding),
            "repo_id": embedding.repo_id,
            "model": embedding.model,
            "chunk_id": embedding.chunk_id,
        },
    )
    session.add(
        CodeChunkEmbeddingRecord(
            id=embedding.id,
            repo_id=embedding.repo_id,
            chunk_id=embedding.chunk_id,
            model=embedding.model,
            dimensions=embedding.dimensions,
            embedding=[],
            content_hash=embedding.content_hash,
            vec_table=vec_table,
            vec_rowid=cursor.lastrowid,
        )
    )


def _embedding_row_matches(
    session,
    row: CodeChunkEmbeddingRecord,
    embedding: CodeChunkEmbeddingRecord,
) -> bool:
    return (
        row.id == embedding.id
        and row.content_hash == embedding.content_hash
        and row.dimensions == embedding.dimensions
        and row.vec_rowid > 0
        and _vector_row_exists(session, row.vec_table, row.vec_rowid)
    )


def _delete_vector_rows(session, rows: list[CodeChunkEmbeddingRecord]) -> None:
    for row in rows:
        if _is_vec_table_name(row.vec_table) and _table_exists(session, row.vec_table):
            session.execute(text(f"DELETE FROM {row.vec_table} WHERE rowid = :rowid"), {"rowid": row.vec_rowid})


def _vector_row_exists(session, vec_table: str, vec_rowid: int) -> bool:
    if not _is_vec_table_name(vec_table) or not _table_exists(session, vec_table):
        return False
    row = session.execute(
        text(f"SELECT 1 FROM {vec_table} WHERE rowid = :vec_rowid"),
        {"vec_rowid": vec_rowid},
    ).first()
    return row is not None


def _delete_existing_vectors(session, repo_id: str, model: str) -> None:
    metadata_rows = session.execute(
        text(
            """
        SELECT DISTINCT vec_table
        FROM code_chunk_embedding
        WHERE repo_id = :repo_id AND model = :model
        """
        ),
        {"repo_id": repo_id, "model": model},
    ).mappings().all()
    table_rows = session.execute(
        text(
            """
        SELECT name AS vec_table
        FROM sqlite_master
        WHERE name LIKE 'code_chunk_embedding_vec_%'
        """
        )
    ).mappings().all()
    vec_tables = {row["vec_table"] for row in [*metadata_rows, *table_rows]}
    for vec_table in vec_tables:
        if _is_vec_table_name(vec_table) and _table_exists(session, vec_table):
            session.execute(
                text(f"DELETE FROM {vec_table} WHERE repo_id = :repo_id AND model = :model"),
                {"repo_id": repo_id, "model": model},
            )


def _ensure_vec_table(session, dimensions: int) -> None:
    vec_table = _vec_table_name(dimensions)
    session.execute(
        text(
            f"""
        CREATE VIRTUAL TABLE IF NOT EXISTS {vec_table}
        USING vec0(
          embedding float[{dimensions}] distance_metric=cosine,
          repo_id text partition key,
          model text partition key,
          chunk_id text
        )
        """
        )
    )


def _load_vector(session, vec_table: str, vec_rowid: int) -> list[float]:
    if not _is_vec_table_name(vec_table) or not _table_exists(session, vec_table):
        return []
    row = session.execute(
        text(f"SELECT embedding FROM {vec_table} WHERE rowid = :vec_rowid"),
        {"vec_rowid": vec_rowid},
    ).mappings().first()
    if row is None:
        return []
    return _deserialize_float32(row["embedding"])


def _serialize_float32(vector: list[float]) -> bytes:
    import sqlite_vec

    return sqlite_vec.serialize_float32(vector)


def _deserialize_float32(blob: bytes) -> list[float]:
    if not blob:
        return []
    return [value for (value,) in struct.iter_unpack("f", blob)]


def _table_exists(session, table_name: str) -> bool:
    row = session.execute(
        text("SELECT 1 FROM sqlite_master WHERE name = :table_name AND type IN ('table', 'virtual table')"),
        {"table_name": table_name},
    ).first()
    return row is not None


def _vec_table_name(dimensions: int) -> str:
    if dimensions <= 0:
        raise ValueError("Vector dimensions must be positive")
    return f"code_chunk_embedding_vec_{dimensions}"


def _is_vec_table_name(table_name: str) -> bool:
    prefix = "code_chunk_embedding_vec_"
    return table_name.startswith(prefix) and table_name[len(prefix) :].isdigit()
