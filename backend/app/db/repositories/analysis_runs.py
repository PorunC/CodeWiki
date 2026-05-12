import json
import uuid
from typing import Any

from backend.app.db.mappers import analysis_run_from_row
from backend.app.db.records import AnalysisRunRecord
from backend.app.db.utils import now_iso


class AnalysisRunRepositoryMixin:
    def create_analysis_run(self, repo_id: str) -> AnalysisRunRecord:
        run = AnalysisRunRecord(
            id=uuid.uuid4().hex,
            repo_id=repo_id,
            status="running",
            started_at=now_iso(),
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
        finished_at = now_iso()
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
        return analysis_run_from_row(row)

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
        return [analysis_run_from_row(row) for row in rows]

    def get_analysis_run(self, run_id: str) -> AnalysisRunRecord | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id, repo_id, status, started_at, finished_at, error, stats_json
                FROM analysis_run WHERE id = ?
                """,
                (run_id,),
            ).fetchone()
        return analysis_run_from_row(row) if row is not None else None

