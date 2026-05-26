import hashlib
import struct

from sqlalchemy import delete, select, text

from backend.app.db.batching import chunks, write_batch_size
from backend.app.db.utils import now_iso
from backend.app.models import CodeChunkEmbeddingRecord, CodeChunkSearchHit


from backend.app.db.repositories.base import RepositorySupportMixin


class CodeChunkEmbeddingRepositoryMixin(RepositorySupportMixin):
    def replace_code_chunk_embeddings(
        self,
        repo_id: str,
        *,
        model: str,
        embeddings: list[CodeChunkEmbeddingRecord],
    ) -> None:
        batch_size = write_batch_size(self.dialect_name)
        with self.orm_session() as session:
            if self.supports_sqlite_vec:
                _delete_existing_vectors(session, repo_id, model)
            elif self.supports_pgvector:
                _delete_existing_pg_vectors(session, repo_id, model)
            session.execute(
                delete(CodeChunkEmbeddingRecord).where(
                    CodeChunkEmbeddingRecord.repo_id == repo_id,
                    CodeChunkEmbeddingRecord.model == model,
                )
            )
            session.commit()
            for index, embedding in enumerate(embeddings, start=1):
                _insert_embedding(
                    session,
                    self.dialect,
                    embedding,
                    dialect_name=self.dialect_name,
                    use_sqlite_vector=self.supports_sqlite_vec,
                    use_pgvector=self.supports_pgvector,
                    pgvector_schema=self.pgvector_schema,
                )
                if index % batch_size == 0:
                    session.commit()
            session.commit()

    def sync_code_chunk_embeddings(
        self,
        repo_id: str,
        *,
        model: str,
        embeddings: list[CodeChunkEmbeddingRecord],
    ) -> None:
        active_by_chunk_id = {embedding.chunk_id: embedding for embedding in embeddings}
        batch_size = write_batch_size(self.dialect_name)
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
                elif _embedding_row_matches(
                    session,
                    row,
                    active,
                    use_sqlite_vector=self.supports_sqlite_vec,
                    use_pgvector=self.supports_pgvector,
                ):
                    kept_chunk_ids.add(row.chunk_id)
                else:
                    changed_rows.append(row)

            rows_to_delete = [*stale_rows, *changed_rows]
            if self.supports_sqlite_vec:
                _delete_vector_rows(session, rows_to_delete)
            elif self.supports_pgvector:
                _delete_pg_vector_rows(session, rows_to_delete)
            if rows_to_delete:
                for delete_batch in chunks(rows_to_delete, batch_size):
                    session.execute(
                        delete(CodeChunkEmbeddingRecord).where(
                            CodeChunkEmbeddingRecord.id.in_([row.id for row in delete_batch]),
                        )
                    )
                    session.commit()

            inserted_count = 0
            for embedding in embeddings:
                if embedding.chunk_id not in kept_chunk_ids:
                    _insert_embedding(
                        session,
                        self.dialect,
                        embedding,
                        dialect_name=self.dialect_name,
                        use_sqlite_vector=self.supports_sqlite_vec,
                        use_pgvector=self.supports_pgvector,
                        pgvector_schema=self.pgvector_schema,
                    )
                    inserted_count += 1
                    if inserted_count % batch_size == 0:
                        session.commit()
            session.commit()

    def list_code_chunk_embeddings(
        self,
        repo_id: str,
        *,
        model: str | None = None,
    ) -> list[CodeChunkEmbeddingRecord]:
        with self.orm_session() as session:
            query = select(CodeChunkEmbeddingRecord).where(
                CodeChunkEmbeddingRecord.repo_id == repo_id
            )
            if model is not None:
                query = query.where(CodeChunkEmbeddingRecord.model == model)
            rows = session.scalars(
                query.order_by(
                    CodeChunkEmbeddingRecord.created_at.desc(), CodeChunkEmbeddingRecord.chunk_id
                )
            ).all()
            for row in rows:
                if self.supports_sqlite_vec:
                    row.embedding = _load_vector(session, row.vec_table, row.vec_rowid)
                elif self.supports_pgvector:
                    row.embedding = _load_pg_vector(session, row.vec_table, row.vec_rowid)
                else:
                    row.embedding = []
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
        if self.supports_pgvector:
            return self._search_code_chunk_embeddings_pgvector(
                repo_id,
                model=model,
                query_embedding=query_embedding,
                limit=limit,
            )
        if not self.supports_sqlite_vec:
            return []
        dimensions = len(query_embedding)
        vec_table = _vec_table_name(dimensions)
        with self.orm_session() as session:
            if not _table_exists(session, vec_table):
                return []
            rows = (
                session.execute(
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
                )
                .mappings()
                .all()
            )

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

    def _search_code_chunk_embeddings_pgvector(
        self,
        repo_id: str,
        *,
        model: str,
        query_embedding: list[float],
        limit: int,
    ) -> list[CodeChunkSearchHit]:
        dimensions = len(query_embedding)
        vec_table = _vec_table_name(dimensions)
        pgvector_schema = _quote_identifier(self.pgvector_schema)
        with self.orm_session() as session:
            if not _pg_vector_table_exists(session, vec_table):
                return []
            rows = (
                session.execute(
                    text(
                        f"""
                    SELECT
                        chunk_id,
                        embedding OPERATOR({pgvector_schema}.<=>)
                          CAST(:embedding AS {pgvector_schema}.vector) AS distance
                    FROM {vec_table}
                    WHERE repo_id = :repo_id
                      AND model = :model
                    ORDER BY embedding OPERATOR({pgvector_schema}.<=>)
                      CAST(:embedding AS {pgvector_schema}.vector)
                    LIMIT :limit
                    """
                    ),
                    {
                        "embedding": _pgvector_literal(query_embedding),
                        "repo_id": repo_id,
                        "model": model,
                        "limit": limit,
                    },
                )
                .mappings()
                .all()
            )

        chunk_ids = [row["chunk_id"] for row in rows]
        chunks = {chunk.id: chunk for chunk in self.get_code_chunks_by_ids(repo_id, chunk_ids)}
        hits: list[CodeChunkSearchHit] = []
        for row in rows:
            chunk = chunks.get(row["chunk_id"])
            if chunk is None:
                continue
            distance = float(row["distance"])
            score = max(0.0, 1.0 - distance)
            hits.append(CodeChunkSearchHit(chunk=chunk, score=score, match_type="pgvector"))
        return hits[:limit]


def _insert_embedding(
    session,
    dialect,
    embedding: CodeChunkEmbeddingRecord,
    *,
    dialect_name: str,
    use_sqlite_vector: bool,
    use_pgvector: bool,
    pgvector_schema: str,
) -> None:
    if embedding.dimensions <= 0 or len(embedding.embedding) != embedding.dimensions:
        raise ValueError(f"Invalid embedding dimensions for chunk {embedding.chunk_id}")

    vec_table = ""
    vec_rowid = _metadata_only_vec_rowid(embedding) if dialect_name == "postgresql" else 0
    if use_sqlite_vector:
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
        vec_rowid = cursor.lastrowid
    elif use_pgvector:
        vec_table = _vec_table_name(embedding.dimensions)
        _ensure_pg_vector_table(session, embedding.dimensions, pgvector_schema=pgvector_schema)
        vec_rowid = session.execute(
            text(
                f"""
                INSERT INTO {vec_table} (embedding, repo_id, model, chunk_id)
                VALUES (:embedding, :repo_id, :model, :chunk_id)
                RETURNING id
                """
            ),
            {
                "embedding": _pgvector_literal(embedding.embedding),
                "repo_id": embedding.repo_id,
                "model": embedding.model,
                "chunk_id": embedding.chunk_id,
            },
        ).scalar_one()
    statement = dialect.insert_ignore(CodeChunkEmbeddingRecord.__table__)
    session.execute(
        statement,
        _embedding_mapping(embedding, vec_table=vec_table, vec_rowid=vec_rowid),
    )


def _embedding_row_matches(
    session,
    row: CodeChunkEmbeddingRecord,
    embedding: CodeChunkEmbeddingRecord,
    *,
    use_sqlite_vector: bool,
    use_pgvector: bool,
) -> bool:
    metadata_matches = (
        row.id == embedding.id
        and row.content_hash == embedding.content_hash
        and row.dimensions == embedding.dimensions
    )
    if not metadata_matches:
        return False
    if not use_sqlite_vector and not use_pgvector:
        return True
    if use_sqlite_vector:
        return row.vec_rowid > 0 and _vector_row_exists(session, row.vec_table, row.vec_rowid)
    return row.vec_rowid > 0 and _pg_vector_row_exists(session, row.vec_table, row.vec_rowid)


def _delete_vector_rows(session, rows: list[CodeChunkEmbeddingRecord]) -> None:
    for row in rows:
        if _is_vec_table_name(row.vec_table) and _table_exists(session, row.vec_table):
            session.execute(
                text(f"DELETE FROM {row.vec_table} WHERE rowid = :rowid"), {"rowid": row.vec_rowid}
            )


def _delete_pg_vector_rows(session, rows: list[CodeChunkEmbeddingRecord]) -> None:
    for row in rows:
        if _is_vec_table_name(row.vec_table) and _pg_vector_table_exists(session, row.vec_table):
            session.execute(
                text(f"DELETE FROM {row.vec_table} WHERE id = :id"), {"id": row.vec_rowid}
            )


def _vector_row_exists(session, vec_table: str, vec_rowid: int) -> bool:
    if not _is_vec_table_name(vec_table) or not _table_exists(session, vec_table):
        return False
    row = session.execute(
        text(f"SELECT 1 FROM {vec_table} WHERE rowid = :vec_rowid"),
        {"vec_rowid": vec_rowid},
    ).first()
    return row is not None


def _delete_existing_vectors(session, repo_id: str, model: str) -> None:
    metadata_rows = (
        session.execute(
            text(
                """
        SELECT DISTINCT vec_table
        FROM code_chunk_embedding
        WHERE repo_id = :repo_id AND model = :model
        """
            ),
            {"repo_id": repo_id, "model": model},
        )
        .mappings()
        .all()
    )
    table_rows = (
        session.execute(
            text(
                """
        SELECT name AS vec_table
        FROM sqlite_master
        WHERE name LIKE 'code_chunk_embedding_vec_%'
        """
            )
        )
        .mappings()
        .all()
    )
    vec_tables = {row["vec_table"] for row in [*metadata_rows, *table_rows]}
    for vec_table in vec_tables:
        if _is_vec_table_name(vec_table) and _table_exists(session, vec_table):
            session.execute(
                text(f"DELETE FROM {vec_table} WHERE repo_id = :repo_id AND model = :model"),
                {"repo_id": repo_id, "model": model},
            )


def _delete_existing_pg_vectors(session, repo_id: str, model: str) -> None:
    rows = (
        session.execute(
            select(CodeChunkEmbeddingRecord).where(
                CodeChunkEmbeddingRecord.repo_id == repo_id,
                CodeChunkEmbeddingRecord.model == model,
            )
        )
        .scalars()
        .all()
    )
    _delete_pg_vector_rows(session, list(rows))


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


def _ensure_pg_vector_table(session, dimensions: int, *, pgvector_schema: str) -> None:
    vec_table = _vec_table_name(dimensions)
    schema = _quote_identifier(pgvector_schema)
    session.execute(
        text(
            f"""
            CREATE TABLE IF NOT EXISTS {vec_table} (
              id BIGSERIAL PRIMARY KEY,
              repo_id TEXT NOT NULL,
              model TEXT NOT NULL,
              chunk_id TEXT NOT NULL,
              embedding {schema}.vector({dimensions}) NOT NULL
            )
            """
        )
    )
    session.execute(
        text(
            f"""
            CREATE INDEX IF NOT EXISTS idx_{vec_table}_repo_model
            ON {vec_table} (repo_id, model)
            """
        )
    )
    session.execute(
        text(
            f"""
            CREATE INDEX IF NOT EXISTS idx_{vec_table}_embedding_hnsw
            ON {vec_table} USING hnsw (embedding {schema}.vector_cosine_ops)
            """
        )
    )


def _load_vector(session, vec_table: str, vec_rowid: int) -> list[float]:
    if not _is_vec_table_name(vec_table) or not _table_exists(session, vec_table):
        return []
    row = (
        session.execute(
            text(f"SELECT embedding FROM {vec_table} WHERE rowid = :vec_rowid"),
            {"vec_rowid": vec_rowid},
        )
        .mappings()
        .first()
    )
    if row is None:
        return []
    return _deserialize_float32(row["embedding"])


def _load_pg_vector(session, vec_table: str, vec_rowid: int) -> list[float]:
    if not _is_vec_table_name(vec_table) or not _pg_vector_table_exists(session, vec_table):
        return []
    row = (
        session.execute(
            text(f"SELECT embedding::text AS embedding FROM {vec_table} WHERE id = :id"),
            {"id": vec_rowid},
        )
        .mappings()
        .first()
    )
    if row is None:
        return []
    return _deserialize_pgvector(row["embedding"])


def _serialize_float32(vector: list[float]) -> bytes:
    import sqlite_vec

    return sqlite_vec.serialize_float32(vector)


def _deserialize_float32(blob: bytes) -> list[float]:
    if not blob:
        return []
    return [value for (value,) in struct.iter_unpack("f", blob)]


def _pgvector_literal(vector: list[float]) -> str:
    return "[" + ",".join(format(float(value), ".9g") for value in vector) + "]"


def _deserialize_pgvector(value: object) -> list[float]:
    if isinstance(value, list):
        return [float(item) for item in value]
    text_value = str(value).strip()
    if not text_value:
        return []
    return [float(item) for item in text_value.removeprefix("[").removesuffix("]").split(",")]


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _table_exists(session, table_name: str) -> bool:
    row = session.execute(
        text(
            "SELECT 1 FROM sqlite_master WHERE name = :table_name AND type IN ('table', 'virtual table')"
        ),
        {"table_name": table_name},
    ).first()
    return row is not None


def _pg_vector_table_exists(session, table_name: str) -> bool:
    if not _is_vec_table_name(table_name):
        return False
    row = session.execute(
        text("SELECT to_regclass(:table_name)"), {"table_name": table_name}
    ).first()
    return row is not None and row[0] is not None


def _pg_vector_row_exists(session, vec_table: str, vec_rowid: int) -> bool:
    if not _is_vec_table_name(vec_table) or not _pg_vector_table_exists(session, vec_table):
        return False
    row = session.execute(
        text(f"SELECT 1 FROM {vec_table} WHERE id = :id"), {"id": vec_rowid}
    ).first()
    return row is not None


def _vec_table_name(dimensions: int) -> str:
    if dimensions <= 0:
        raise ValueError("Vector dimensions must be positive")
    return f"code_chunk_embedding_vec_{dimensions}"


def _is_vec_table_name(table_name: str) -> bool:
    prefix = "code_chunk_embedding_vec_"
    return table_name.startswith(prefix) and table_name[len(prefix) :].isdigit()


def _metadata_only_vec_rowid(embedding: CodeChunkEmbeddingRecord) -> int:
    digest = hashlib.sha256(embedding.id.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % (2**63 - 1) + 1


def _embedding_mapping(
    embedding: CodeChunkEmbeddingRecord,
    *,
    vec_table: str,
    vec_rowid: int,
) -> dict[str, object]:
    return {
        "id": embedding.id,
        "repo_id": embedding.repo_id,
        "chunk_id": embedding.chunk_id,
        "model": embedding.model,
        "dimensions": embedding.dimensions,
        "vec_table": vec_table,
        "vec_rowid": vec_rowid,
        "content_hash": embedding.content_hash,
        "created_at": embedding.created_at or now_iso(),
    }
