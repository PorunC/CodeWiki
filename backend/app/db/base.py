import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.db.dialects import DatabaseDialect
from backend.app.db.schema import AUXILIARY_SCHEMA_SQL
from backend.app.db.utils import sqlite_path_from_url, sync_database_url
from backend.app.models import Base

SQLITE_BUSY_TIMEOUT_SECONDS = 30
SQLITE_BUSY_TIMEOUT_MS = SQLITE_BUSY_TIMEOUT_SECONDS * 1000


@dataclass(frozen=True)
class ColumnPatch:
    table: str
    column: str
    sqlite_ddl: str
    postgres_ddl: str

    def ddl(self, dialect_name: str) -> str:
        if dialect_name == "postgresql":
            return self.postgres_ddl
        return self.sqlite_ddl


COLUMN_PATCHES = (
    ColumnPatch("repo", "git_url", "git_url TEXT", "git_url TEXT"),
    ColumnPatch("repo", "commit_hash", "commit_hash TEXT", "commit_hash TEXT"),
    ColumnPatch(
        "llm_run",
        "response_content",
        "response_content TEXT NOT NULL DEFAULT ''",
        "response_content TEXT NOT NULL DEFAULT ''",
    ),
    ColumnPatch(
        "llm_run",
        "response_usage_json",
        "response_usage_json TEXT NOT NULL DEFAULT '{}'",
        "response_usage_json TEXT NOT NULL DEFAULT '{}'",
    ),
    ColumnPatch(
        "doc_catalog",
        "language_code",
        "language_code TEXT NOT NULL DEFAULT 'en'",
        "language_code TEXT NOT NULL DEFAULT 'en'",
    ),
    ColumnPatch(
        "doc_page",
        "language_code",
        "language_code TEXT NOT NULL DEFAULT 'en'",
        "language_code TEXT NOT NULL DEFAULT 'en'",
    ),
    ColumnPatch("graph_community", "parent_id", "parent_id TEXT", "parent_id TEXT"),
    ColumnPatch("graph_community", "rank", "rank INTEGER DEFAULT 0", "rank INTEGER DEFAULT 0"),
)


class BaseStore:
    dialect_name: str
    supports_fts5 = False
    supports_postgres_text_search = False
    supports_sqlite_vec = False

    def __init__(self, database_url: str) -> None:
        self.database_url = sync_database_url(database_url)
        self.engine = self._create_engine()
        self.session_factory = sessionmaker(self.engine, expire_on_commit=False)
        self.dialect = DatabaseDialect(self.dialect_name)
        self.ensure_schema()

    @contextmanager
    def orm_session(self) -> Iterator[Session]:
        with self.session_factory() as session:
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise

    @contextmanager
    def sql_connection(self):
        with self.engine.begin() as connection:
            yield connection

    def raw_connection(self):
        return self.engine.raw_connection()

    def close(self) -> None:
        self.engine.dispose()

    def ensure_schema(self) -> None:
        Base.metadata.create_all(self.engine)
        self._ensure_column_patches()
        self._ensure_indexes()

    def _create_engine(self) -> Engine:
        return create_engine(self.database_url, future=True)

    def _ensure_column_patches(self) -> None:
        inspector = inspect(self.engine)
        with self.engine.begin() as connection:
            for patch in COLUMN_PATCHES:
                if not inspector.has_table(patch.table):
                    continue
                columns = {column["name"] for column in inspector.get_columns(patch.table)}
                if patch.column in columns:
                    continue
                clause = "ADD COLUMN IF NOT EXISTS" if self.dialect_name == "postgresql" else "ADD COLUMN"
                connection.execute(
                    text(f"ALTER TABLE {patch.table} {clause} {patch.ddl(self.dialect_name)}")
                )

    def _ensure_indexes(self) -> None:
        with self.engine.begin() as connection:
            connection.execute(text("DROP INDEX IF EXISTS idx_doc_page_slug"))
            connection.execute(
                text(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_doc_page_slug_language
                    ON doc_page (repo_id, language_code, slug)
                    """
                )
            )


class SQLiteStoreBase(BaseStore):
    dialect_name = "sqlite"
    supports_fts5 = True
    supports_sqlite_vec = True

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        super().__init__(f"sqlite:///{self.database_path}")

    @classmethod
    def from_url(cls, database_url: str):
        return cls(sqlite_path_from_url(database_url))

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.database_path,
            timeout=SQLITE_BUSY_TIMEOUT_SECONDS,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        self._configure_connection(connection)
        self._load_sqlite_vec(connection)
        return connection

    def ensure_schema(self) -> None:
        super().ensure_schema()
        with self.connect() as connection:
            connection.executescript(AUXILIARY_SCHEMA_SQL)
            self._sync_code_node_fts_if_needed(connection)

    def _create_engine(self) -> Engine:
        engine = create_engine(
            self.database_url,
            connect_args={
                "timeout": SQLITE_BUSY_TIMEOUT_SECONDS,
                "check_same_thread": False,
            },
            future=True,
        )

        @event.listens_for(engine, "connect")
        def configure_connection(dbapi_connection, _connection_record) -> None:
            self._configure_connection(dbapi_connection)
            self._load_sqlite_vec(dbapi_connection)

        return engine

    def _configure_connection(self, connection: sqlite3.Connection) -> None:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")

    def _load_sqlite_vec(self, connection: sqlite3.Connection) -> None:
        try:
            import sqlite_vec
        except ImportError as exc:
            raise RuntimeError(
                "sqlite-vec is required for CodeWiki vector search. "
                "Install dependencies from pyproject.toml."
            ) from exc

        connection.enable_load_extension(True)
        try:
            sqlite_vec.load(connection)
        finally:
            connection.enable_load_extension(False)

    def _sync_code_node_fts_if_needed(self, connection: sqlite3.Connection) -> None:
        node_count = connection.execute("SELECT COUNT(*) FROM code_node").fetchone()[0]
        fts_count = connection.execute("SELECT COUNT(*) FROM code_node_fts").fetchone()[0]
        if node_count == fts_count:
            return

        connection.execute("DELETE FROM code_node_fts")
        connection.execute(
            """
            INSERT INTO code_node_fts (
              id, repo_id, type, name, file_path, language, symbol_id, summary, signature, docstring
            )
            SELECT n.id, n.repo_id, n.type, n.name, n.file_path,
                   COALESCE(n.language, ''), COALESCE(n.symbol_id, ''),
                   COALESCE(n.summary, ''), '', ''
            FROM code_node n
            """
        )


class PostgresStoreBase(BaseStore):
    dialect_name = "postgresql"
    supports_postgres_text_search = True

    @classmethod
    def from_url(cls, database_url: str):
        return cls(database_url)

    def ensure_schema(self) -> None:
        super().ensure_schema()
        self._ensure_text_search_indexes()

    def connect(self):
        raise NotImplementedError(
            "Direct sqlite3-style connect() is not supported for PostgreSQL; "
            "use orm_session(), sql_connection(), or SQLAlchemy inspector helpers."
        )

    def _create_engine(self) -> Engine:
        return create_engine(
            self.database_url,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
            pool_recycle=1800,
            future=True,
        )

    def _ensure_text_search_indexes(self) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS idx_code_node_search_vector
                    ON code_node USING GIN (
                        to_tsvector(
                            'simple',
                            coalesce(name, '') || ' ' ||
                            coalesce(symbol_id, '') || ' ' ||
                            coalesce(file_path, '') || ' ' ||
                            coalesce(summary, '')
                        )
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS idx_code_chunk_search_vector
                    ON code_chunk USING GIN (
                        to_tsvector(
                            'simple',
                            coalesce(content, '') || ' ' ||
                            coalesce(file_path, '')
                        )
                    )
                    """
                )
            )
