import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from backend.app.config import get_settings
from backend.app.services.graph_builder import CodeGraphEdge, CodeGraphNode
from backend.app.services.repo_scanner import RepoDescriptor


@dataclass(frozen=True)
class AnalysisRunRecord:
    id: str
    repo_id: str
    status: str
    started_at: str | None
    finished_at: str | None
    error: str | None
    stats: dict[str, Any]


class SQLiteStore:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.ensure_schema()

    @classmethod
    def from_url(cls, database_url: str) -> "SQLiteStore":
        return cls(_sqlite_path_from_url(database_url))

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def ensure_schema(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS repo (
                  id TEXT PRIMARY KEY,
                  name TEXT NOT NULL,
                  path TEXT NOT NULL,
                  source_type TEXT NOT NULL DEFAULT 'local',
                  git_url TEXT,
                  commit_hash TEXT,
                  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS analysis_run (
                  id TEXT PRIMARY KEY,
                  repo_id TEXT NOT NULL REFERENCES repo(id) ON DELETE CASCADE,
                  status TEXT NOT NULL DEFAULT 'pending',
                  started_at TEXT,
                  finished_at TEXT,
                  error TEXT,
                  stats_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_analysis_run_repo
                  ON analysis_run(repo_id, started_at);

                CREATE TABLE IF NOT EXISTS code_node (
                  id TEXT PRIMARY KEY,
                  repo_id TEXT NOT NULL REFERENCES repo(id) ON DELETE CASCADE,
                  type TEXT NOT NULL,
                  name TEXT NOT NULL,
                  file_path TEXT NOT NULL DEFAULT '',
                  start_line INTEGER,
                  end_line INTEGER,
                  language TEXT,
                  symbol_id TEXT,
                  summary TEXT,
                  hash TEXT NOT NULL DEFAULT '',
                  metadata_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_code_node_repo ON code_node(repo_id);
                CREATE INDEX IF NOT EXISTS idx_code_node_type ON code_node(repo_id, type);
                CREATE INDEX IF NOT EXISTS idx_code_node_file ON code_node(repo_id, file_path);

                CREATE TABLE IF NOT EXISTS code_edge (
                  id TEXT PRIMARY KEY,
                  repo_id TEXT NOT NULL REFERENCES repo(id) ON DELETE CASCADE,
                  source_id TEXT NOT NULL REFERENCES code_node(id) ON DELETE CASCADE,
                  target_id TEXT NOT NULL REFERENCES code_node(id) ON DELETE CASCADE,
                  type TEXT NOT NULL,
                  confidence REAL NOT NULL DEFAULT 1.0,
                  weight REAL NOT NULL DEFAULT 1.0,
                  is_inferred INTEGER NOT NULL DEFAULT 0,
                  metadata_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_code_edge_repo ON code_edge(repo_id);
                CREATE INDEX IF NOT EXISTS idx_code_edge_source ON code_edge(source_id);
                CREATE INDEX IF NOT EXISTS idx_code_edge_target ON code_edge(target_id);
                """
            )

    def upsert_repo(self, repo: RepoDescriptor) -> RepoDescriptor:
        now = _now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO repo (id, name, path, source_type, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  name = excluded.name,
                  path = excluded.path,
                  source_type = excluded.source_type,
                  updated_at = excluded.updated_at
                """,
                (repo.id, repo.name, repo.path, repo.source_type, now),
            )
        return repo

    def get_repo(self, repo_id: str) -> RepoDescriptor | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT id, name, path, source_type FROM repo WHERE id = ?",
                (repo_id,),
            ).fetchone()
        if row is None:
            return None
        return RepoDescriptor(
            id=row["id"],
            name=row["name"],
            path=row["path"],
            source_type=row["source_type"],
        )

    def list_repos(self) -> list[RepoDescriptor]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT id, name, path, source_type FROM repo ORDER BY updated_at DESC, name"
            ).fetchall()
        return [
            RepoDescriptor(
                id=row["id"],
                name=row["name"],
                path=row["path"],
                source_type=row["source_type"],
            )
            for row in rows
        ]

    def create_analysis_run(self, repo_id: str) -> AnalysisRunRecord:
        run = AnalysisRunRecord(
            id=uuid.uuid4().hex,
            repo_id=repo_id,
            status="running",
            started_at=_now(),
            finished_at=None,
            error=None,
            stats={},
        )
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO analysis_run (id, repo_id, status, started_at, stats_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (run.id, run.repo_id, run.status, run.started_at, json.dumps(run.stats)),
            )
        return run

    def finish_analysis_run(
        self,
        run_id: str,
        *,
        status: str,
        stats: dict[str, Any],
        error: str | None = None,
    ) -> AnalysisRunRecord:
        finished_at = _now()
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE analysis_run
                SET status = ?, finished_at = ?, error = ?, stats_json = ?
                WHERE id = ?
                """,
                (status, finished_at, error, json.dumps(stats, sort_keys=True), run_id),
            )
            row = connection.execute(
                """
                SELECT id, repo_id, status, started_at, finished_at, error, stats_json
                FROM analysis_run WHERE id = ?
                """,
                (run_id,),
            ).fetchone()
        return _analysis_run_from_row(row)

    def list_analysis_runs(self, repo_id: str) -> list[AnalysisRunRecord]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, repo_id, status, started_at, finished_at, error, stats_json
                FROM analysis_run
                WHERE repo_id = ?
                ORDER BY started_at DESC
                """,
                (repo_id,),
            ).fetchall()
        return [_analysis_run_from_row(row) for row in rows]

    def get_analysis_run(self, run_id: str) -> AnalysisRunRecord | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id, repo_id, status, started_at, finished_at, error, stats_json
                FROM analysis_run WHERE id = ?
                """,
                (run_id,),
            ).fetchone()
        return _analysis_run_from_row(row) if row is not None else None

    def replace_graph(
        self,
        repo_id: str,
        *,
        nodes: list[CodeGraphNode],
        edges: list[CodeGraphEdge],
    ) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM code_edge WHERE repo_id = ?", (repo_id,))
            connection.execute("DELETE FROM code_node WHERE repo_id = ?", (repo_id,))
            connection.executemany(
                """
                INSERT INTO code_node (
                  id, repo_id, type, name, file_path, start_line, end_line,
                  language, symbol_id, summary, hash, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        node.id,
                        node.repo_id,
                        node.type,
                        node.name,
                        node.file_path,
                        node.start_line,
                        node.end_line,
                        node.language,
                        node.symbol_id,
                        node.summary,
                        node.hash,
                        json.dumps(node.metadata, sort_keys=True),
                    )
                    for node in nodes
                ],
            )
            connection.executemany(
                """
                INSERT INTO code_edge (
                  id, repo_id, source_id, target_id, type,
                  confidence, weight, is_inferred, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        edge.id,
                        edge.repo_id,
                        edge.source_id,
                        edge.target_id,
                        edge.type,
                        edge.confidence,
                        edge.weight,
                        int(edge.is_inferred),
                        json.dumps(edge.metadata, sort_keys=True),
                    )
                    for edge in edges
                ],
            )

    def get_graph(self, repo_id: str) -> tuple[list[CodeGraphNode], list[CodeGraphEdge]]:
        with self.connect() as connection:
            node_rows = connection.execute(
                """
                SELECT id, repo_id, type, name, file_path, start_line, end_line,
                       language, symbol_id, summary, hash, metadata_json
                FROM code_node
                WHERE repo_id = ?
                ORDER BY type, file_path, name
                """,
                (repo_id,),
            ).fetchall()
            edge_rows = connection.execute(
                """
                SELECT id, repo_id, source_id, target_id, type,
                       confidence, weight, is_inferred, metadata_json
                FROM code_edge
                WHERE repo_id = ?
                ORDER BY type, source_id, target_id
                """,
                (repo_id,),
            ).fetchall()
        return (
            [_node_from_row(row) for row in node_rows],
            [_edge_from_row(row) for row in edge_rows],
        )


@lru_cache
def get_store() -> SQLiteStore:
    return SQLiteStore.from_url(get_settings().database_url)


def _sqlite_path_from_url(database_url: str) -> Path:
    for prefix in ("sqlite+aiosqlite:///", "sqlite:///"):
        if database_url.startswith(prefix):
            return Path(database_url.removeprefix(prefix)).expanduser()
    raise ValueError(f"Only sqlite database URLs are supported: {database_url}")


def _analysis_run_from_row(row: sqlite3.Row) -> AnalysisRunRecord:
    return AnalysisRunRecord(
        id=row["id"],
        repo_id=row["repo_id"],
        status=row["status"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        error=row["error"],
        stats=json.loads(row["stats_json"] or "{}"),
    )


def _node_from_row(row: sqlite3.Row) -> CodeGraphNode:
    return CodeGraphNode(
        id=row["id"],
        repo_id=row["repo_id"],
        type=row["type"],
        name=row["name"],
        file_path=row["file_path"],
        start_line=row["start_line"],
        end_line=row["end_line"],
        language=row["language"],
        symbol_id=row["symbol_id"],
        summary=row["summary"],
        hash=row["hash"],
        metadata=json.loads(row["metadata_json"] or "{}"),
    )


def _edge_from_row(row: sqlite3.Row) -> CodeGraphEdge:
    return CodeGraphEdge(
        id=row["id"],
        repo_id=row["repo_id"],
        source_id=row["source_id"],
        target_id=row["target_id"],
        type=row["type"],
        confidence=row["confidence"],
        weight=row["weight"],
        is_inferred=bool(row["is_inferred"]),
        metadata=json.loads(row["metadata_json"] or "{}"),
    )


def _now() -> str:
    return datetime.now(tz=UTC).isoformat()
