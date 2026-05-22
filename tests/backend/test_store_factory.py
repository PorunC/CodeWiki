from pathlib import Path

import pytest
from sqlalchemy.dialects import postgresql

from backend.app.db.dialects import DatabaseDialect
from backend.app.db.store import PostgresStore, SQLiteStore, create_store
from backend.app.db.utils import database_backend_from_url, sync_database_url
from backend.app.models import CodeChunkRecord


def test_database_backend_from_url_accepts_sqlite_and_postgres() -> None:
    assert database_backend_from_url("sqlite:///tmp/codewiki.sqlite3") == "sqlite"
    assert database_backend_from_url("sqlite+aiosqlite:///tmp/codewiki.sqlite3") == "sqlite"
    assert database_backend_from_url("postgresql://u:p@localhost/codewiki") == "postgresql"
    assert database_backend_from_url("postgresql+psycopg://u:p@localhost/codewiki") == "postgresql"


def test_database_backend_from_url_rejects_unknown_scheme() -> None:
    with pytest.raises(ValueError, match="Unsupported database URL scheme"):
        database_backend_from_url("mysql://localhost/codewiki")


def test_sync_database_url_normalizes_async_or_default_driver_names() -> None:
    assert sync_database_url("sqlite+aiosqlite:///tmp/codewiki.sqlite3") == (
        "sqlite:///tmp/codewiki.sqlite3"
    )
    assert sync_database_url("postgresql://u:p@localhost/codewiki") == (
        "postgresql+psycopg://u:p@localhost/codewiki"
    )


def test_create_store_dispatches_sqlite(tmp_path: Path) -> None:
    store = create_store(f"sqlite+aiosqlite:///{tmp_path / 'codewiki.sqlite3'}")
    try:
        assert isinstance(store, SQLiteStore)
    finally:
        store.close()


def test_create_store_dispatches_postgres_without_opening_real_connection(monkeypatch) -> None:
    sentinel = object()

    def fake_from_url(database_url: str) -> object:
        assert database_url == "postgresql+psycopg://codewiki:codewiki@localhost/codewiki"
        return sentinel

    monkeypatch.setattr(PostgresStore, "from_url", fake_from_url)

    assert create_store("postgresql+psycopg://codewiki:codewiki@localhost/codewiki") is sentinel


def test_insert_ignore_can_target_any_unique_constraint() -> None:
    statement = DatabaseDialect("postgresql").insert_ignore(CodeChunkRecord.__table__)

    compiled = str(statement.compile(dialect=postgresql.dialect()))

    assert "ON CONFLICT DO NOTHING" in compiled
