import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from typing import Mapping

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.db.schema import AUXILIARY_SCHEMA_SQL
from backend.app.db.utils import sqlite_path_from_url
from backend.app.models import Base

SQLITE_BUSY_TIMEOUT_SECONDS = 30
SQLITE_BUSY_TIMEOUT_MS = SQLITE_BUSY_TIMEOUT_SECONDS * 1000


class BaseSQLiteStore:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = self._create_engine()
        self.session_factory = sessionmaker(self.engine, expire_on_commit=False)
        self.ensure_schema()

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

    @contextmanager
    def orm_session(self) -> Iterator[Session]:
        with self.session_factory() as session:
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise

    def ensure_schema(self) -> None:
        Base.metadata.create_all(self.engine)
        with self.connect() as connection:
            connection.executescript(AUXILIARY_SCHEMA_SQL)
            connection.execute(
                """
                INSERT INTO code_node_fts (
                  id, repo_id, type, name, file_path, language, symbol_id, summary, signature, docstring
                )
                SELECT n.id, n.repo_id, n.type, n.name, n.file_path,
                       COALESCE(n.language, ''), COALESCE(n.symbol_id, ''),
                       COALESCE(n.summary, ''), '', ''
                FROM code_node n
                WHERE NOT EXISTS (
                  SELECT 1 FROM code_node_fts f WHERE f.id = n.id
                )
                """
            )
            self._ensure_columns(
                connection,
                "repo",
                {
                    "git_url": "TEXT",
                    "commit_hash": "TEXT",
                },
            )
            self._ensure_columns(
                connection,
                "llm_run",
                {
                    "response_content": "TEXT NOT NULL DEFAULT ''",
                    "response_usage_json": "TEXT NOT NULL DEFAULT '{}'",
                },
            )
            self._ensure_columns(
                connection,
                "doc_catalog",
                {
                    "language_code": "TEXT NOT NULL DEFAULT 'en'",
                },
            )
            self._ensure_columns(
                connection,
                "doc_page",
                {
                    "language_code": "TEXT NOT NULL DEFAULT 'en'",
                },
            )
            self._ensure_columns(
                connection,
                "graph_community",
                {
                    "parent_id": "TEXT",
                    "rank": "INTEGER DEFAULT 0",
                },
            )
            connection.execute("DROP INDEX IF EXISTS idx_doc_page_slug")
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_doc_page_slug_language
                ON doc_page (repo_id, language_code, slug)
                """
            )

    def _create_engine(self) -> Engine:
        engine = create_engine(
            f"sqlite:///{self.database_path}",
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

    def _ensure_columns(
        self,
        connection: sqlite3.Connection,
        table_name: str,
        columns: Mapping[str, str],
    ) -> None:
        existing = {
            row["name"]
            for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        for column_name, column_type in columns.items():
            if column_name not in existing:
                connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")
