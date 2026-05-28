import uuid
from typing import Any

from sqlalchemy import select

from backend.app.models import AnalysisRunRecord
from backend.app.db.utils import now_iso


from backend.app.db.repositories.base import RepositorySupportMixin


class AnalysisRunRepositoryMixin(RepositorySupportMixin):
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
        with self.orm_session() as session:
            session.add(run)
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
        with self.orm_session() as session:
            run = session.get(AnalysisRunRecord, run_id)
            if run is None:
                raise ValueError(f"Analysis run not found: {run_id}")
            run.status = status
            run.finished_at = finished_at
            run.error = error
            run.stats = stats
            return run

    def update_analysis_run_stats(
        self,
        run_id: str,
        stats: dict[str, Any],
    ) -> AnalysisRunRecord:
        with self.orm_session() as session:
            run = session.get(AnalysisRunRecord, run_id)
            if run is None:
                raise ValueError(f"Analysis run not found: {run_id}")
            run.stats = stats
            return run

    def list_analysis_runs(self, repo_id: str) -> list[AnalysisRunRecord]:
        with self.orm_session() as session:
            return list(
                session.scalars(
                    select(AnalysisRunRecord)
                    .where(AnalysisRunRecord.repo_id == repo_id)
                    .order_by(AnalysisRunRecord.started_at.desc())
                )
            )

    def get_analysis_run(self, run_id: str) -> AnalysisRunRecord | None:
        with self.orm_session() as session:
            return session.get(AnalysisRunRecord, run_id)
