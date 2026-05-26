from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, cast

from sqlalchemy.orm import Session

from backend.app.db.dialects import DatabaseDialect
from backend.app.models import CodeChunkRecord


class RepositorySupportMixin:
    dialect: DatabaseDialect
    dialect_name: str
    supports_fts5: bool
    supports_postgres_text_search: bool
    supports_pgvector: bool
    pgvector_schema: str
    supports_sqlite_vec: bool

    if TYPE_CHECKING:

        @contextmanager
        def orm_session(self) -> Iterator[Session]:
            yield cast(Session, None)

        def get_code_chunks_by_ids(
            self,
            repo_id: str,
            chunk_ids: list[str],
        ) -> list[CodeChunkRecord]: ...
