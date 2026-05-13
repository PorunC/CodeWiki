import sqlite3
import struct

from backend.app.db.records import CodeChunkEmbeddingRecord, CodeChunkSearchHit
from backend.app.db.mappers import code_chunk_embedding_from_row


class CodeChunkEmbeddingRepositoryMixin:
    def replace_code_chunk_embeddings(
        self,
        repo_id: str,
        *,
        model: str,
        embeddings: list[CodeChunkEmbeddingRecord],
    ) -> None:
        with self.connect() as connection:
            _delete_existing_vectors(connection, repo_id, model)
            connection.execute(
                "DELETE FROM code_chunk_embedding WHERE repo_id = ? AND model = ?",
                (repo_id, model),
            )
            for embedding in embeddings:
                if embedding.dimensions <= 0 or len(embedding.embedding) != embedding.dimensions:
                    raise ValueError(f"Invalid embedding dimensions for chunk {embedding.chunk_id}")

                vec_table = _vec_table_name(embedding.dimensions)
                _ensure_vec_table(connection, embedding.dimensions)
                cursor = connection.execute(
                    f"""
                    INSERT INTO {vec_table} (embedding, repo_id, model, chunk_id)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        _serialize_float32(embedding.embedding),
                        embedding.repo_id,
                        embedding.model,
                        embedding.chunk_id,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO code_chunk_embedding (
                      id, repo_id, chunk_id, model, dimensions,
                      vec_table, vec_rowid, content_hash
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        embedding.id,
                        embedding.repo_id,
                        embedding.chunk_id,
                        embedding.model,
                        embedding.dimensions,
                        vec_table,
                        cursor.lastrowid,
                        embedding.content_hash,
                    ),
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
                       vec_table, vec_rowid, content_hash, created_at
                FROM code_chunk_embedding
                WHERE {where}
                ORDER BY created_at DESC, chunk_id
                """,
                params,
            ).fetchall()
            return [
                CodeChunkEmbeddingRecord(
                    **{
                        **code_chunk_embedding_from_row(row).__dict__,
                        "embedding": _load_vector(connection, row["vec_table"], row["vec_rowid"]),
                    }
                )
                for row in rows
            ]

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
        with self.connect() as connection:
            if not _table_exists(connection, vec_table):
                return []
            rows = connection.execute(
                f"""
                SELECT chunk_id, distance
                FROM {vec_table}
                WHERE embedding MATCH ?
                  AND repo_id = ?
                  AND model = ?
                  AND k = ?
                ORDER BY distance
                """,
                (_serialize_float32(query_embedding), repo_id, model, limit),
            ).fetchall()

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


def _delete_existing_vectors(connection: sqlite3.Connection, repo_id: str, model: str) -> None:
    metadata_rows = connection.execute(
        """
        SELECT DISTINCT vec_table
        FROM code_chunk_embedding
        WHERE repo_id = ? AND model = ?
        """,
        (repo_id, model),
    ).fetchall()
    table_rows = connection.execute(
        """
        SELECT name AS vec_table
        FROM sqlite_master
        WHERE name LIKE 'code_chunk_embedding_vec_%'
        """
    ).fetchall()
    vec_tables = {row["vec_table"] for row in [*metadata_rows, *table_rows]}
    for vec_table in vec_tables:
        if _is_vec_table_name(vec_table) and _table_exists(connection, vec_table):
            connection.execute(
                f"DELETE FROM {vec_table} WHERE repo_id = ? AND model = ?",
                (repo_id, model),
            )


def _ensure_vec_table(connection: sqlite3.Connection, dimensions: int) -> None:
    vec_table = _vec_table_name(dimensions)
    connection.execute(
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


def _load_vector(connection: sqlite3.Connection, vec_table: str, vec_rowid: int) -> list[float]:
    if not _is_vec_table_name(vec_table) or not _table_exists(connection, vec_table):
        return []
    row = connection.execute(
        f"SELECT embedding FROM {vec_table} WHERE rowid = ?",
        (vec_rowid,),
    ).fetchone()
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


def _table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE name = ? AND type IN ('table', 'virtual table')",
        (table_name,),
    ).fetchone()
    return row is not None


def _vec_table_name(dimensions: int) -> str:
    if dimensions <= 0:
        raise ValueError("Vector dimensions must be positive")
    return f"code_chunk_embedding_vec_{dimensions}"


def _is_vec_table_name(table_name: str) -> bool:
    prefix = "code_chunk_embedding_vec_"
    return table_name.startswith(prefix) and table_name[len(prefix) :].isdigit()
