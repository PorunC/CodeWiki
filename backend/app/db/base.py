import sqlite3
from pathlib import Path
from typing import Mapping

from backend.app.db.schema import SCHEMA_SQL
from backend.app.db.utils import sqlite_path_from_url


class BaseSQLiteStore:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.ensure_schema()

    @classmethod
    def from_url(cls, database_url: str):
        return cls(sqlite_path_from_url(database_url))

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def ensure_schema(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA_SQL)
            self._ensure_columns(
                connection,
                "repo",
                {
                    "git_url": "TEXT",
                    "commit_hash": "TEXT",
                },
            )

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
