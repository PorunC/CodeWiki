from functools import lru_cache

from backend.app.config import get_settings
from backend.app.db.base import BaseSQLiteStore
from backend.app.db.repositories import (
    AnalysisRunRepositoryMixin,
    CodeGraphRepositoryMixin,
    GraphRAGRepositoryMixin,
    LLMRunRepositoryMixin,
    RepoRepositoryMixin,
    WikiRepositoryMixin,
)


class SQLiteStore(
    RepoRepositoryMixin,
    AnalysisRunRepositoryMixin,
    CodeGraphRepositoryMixin,
    GraphRAGRepositoryMixin,
    WikiRepositoryMixin,
    LLMRunRepositoryMixin,
    BaseSQLiteStore,
):
    """SQLite persistence facade composed from small repository mixins."""


@lru_cache
def get_store() -> SQLiteStore:
    return SQLiteStore.from_url(get_settings().database_url)

