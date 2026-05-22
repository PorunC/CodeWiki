from functools import lru_cache
from typing import TypeAlias

from backend.app.config import get_settings
from backend.app.db.base import PostgresStoreBase, SQLiteStoreBase
from backend.app.db.repositories import (
    AnalysisRunRepositoryMixin,
    CodeGraphRepositoryMixin,
    GraphRAGRepositoryMixin,
    LLMRunRepositoryMixin,
    RepoRepositoryMixin,
    WikiRepositoryMixin,
)
from backend.app.db.utils import database_backend_from_url


class StoreRepositoryMixin(
    RepoRepositoryMixin,
    AnalysisRunRepositoryMixin,
    CodeGraphRepositoryMixin,
    GraphRAGRepositoryMixin,
    WikiRepositoryMixin,
    LLMRunRepositoryMixin,
):
    """Common repository API shared by all database backends."""


class SQLiteStore(StoreRepositoryMixin, SQLiteStoreBase):
    """SQLite persistence facade composed from small repository mixins."""


class PostgresStore(StoreRepositoryMixin, PostgresStoreBase):
    """PostgreSQL persistence facade composed from small repository mixins."""


CodeWikiStore: TypeAlias = SQLiteStore | PostgresStore


def create_store(database_url: str) -> CodeWikiStore:
    backend = database_backend_from_url(database_url)
    if backend == "sqlite":
        return SQLiteStore.from_url(database_url)
    if backend == "postgresql":
        return PostgresStore.from_url(database_url)
    raise AssertionError(f"Unhandled database backend: {backend}")


@lru_cache
def get_store() -> CodeWikiStore:
    return create_store(get_settings().database_url)
