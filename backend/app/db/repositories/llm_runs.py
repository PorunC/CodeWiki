import uuid
from typing import Any

from sqlalchemy import select

from backend.app.models import LLMRunRecord
from backend.app.db.utils import now_iso


class LLMRunRepositoryMixin:
    def record_llm_run(
        self,
        repo_id: str,
        *,
        task_type: str,
        model: str,
        input_hash: str,
        cache_key: str,
        provider: str | None = None,
        model_alias: str | None = None,
        prompt_version: str | None = None,
        tokens_in: int = 0,
        tokens_out: int = 0,
        cost_usd: float | None = None,
        duration_ms: int | None = None,
        response_content: str = "",
        response_usage: dict[str, Any] | None = None,
        cached: bool = False,
        status: str = "success",
        error: str | None = None,
    ) -> LLMRunRecord:
        record = LLMRunRecord(
            id=uuid.uuid4().hex,
            repo_id=repo_id,
            task_type=task_type,
            provider=provider,
            model=model,
            model_alias=model_alias,
            prompt_version=prompt_version,
            input_hash=input_hash,
            cache_key=cache_key,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost_usd,
            duration_ms=duration_ms,
            response_content=response_content,
            response_usage=response_usage or {},
            cached=cached,
            status=status,
            error=error,
            created_at=now_iso(),
        )
        with self.orm_session() as session:
            session.add(record)
        return record

    def get_cached_llm_run(
        self,
        repo_id: str,
        *,
        task_type: str,
        cache_key: str,
        input_hash: str,
        model: str | None = None,
        prompt_version: str | None = None,
    ) -> LLMRunRecord | None:
        with self.orm_session() as session:
            query = select(LLMRunRecord).where(
                LLMRunRecord.repo_id == repo_id,
                LLMRunRecord.task_type == task_type,
                LLMRunRecord.cache_key == cache_key,
                LLMRunRecord.input_hash == input_hash,
                LLMRunRecord.status == "success",
                LLMRunRecord.response_content != "",
            )
            if model is not None:
                query = query.where(LLMRunRecord.model == model)
            if prompt_version is not None:
                query = query.where(LLMRunRecord.prompt_version == prompt_version)
            return session.scalars(query.order_by(LLMRunRecord.created_at.desc()).limit(1)).first()

    def update_llm_run_status(
        self,
        run_id: str,
        *,
        status: str,
        error: str | None = None,
    ) -> LLMRunRecord | None:
        with self.orm_session() as session:
            record = session.get(LLMRunRecord, run_id)
            if record is None:
                return None
            record.status = status
            record.error = error
            return record

    def list_llm_runs(self, repo_id: str, *, task_type: str | None = None) -> list[LLMRunRecord]:
        with self.orm_session() as session:
            query = select(LLMRunRecord).where(LLMRunRecord.repo_id == repo_id)
            if task_type:
                query = query.where(LLMRunRecord.task_type == task_type)
            return list(session.scalars(query.order_by(LLMRunRecord.created_at.desc())))
