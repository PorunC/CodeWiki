import uuid
from typing import Any

from backend.app.db.mappers import llm_run_from_row
from backend.app.db.records import LLMRunRecord
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
            cached=cached,
            status=status,
            error=error,
            created_at=now_iso(),
        )
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO llm_run (
                  id, repo_id, task_type, provider, model, model_alias, prompt_version,
                  input_hash, cache_key, tokens_in, tokens_out, cost_usd, duration_ms,
                  cached, status, error, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.repo_id,
                    record.task_type,
                    record.provider,
                    record.model,
                    record.model_alias,
                    record.prompt_version,
                    record.input_hash,
                    record.cache_key,
                    record.tokens_in,
                    record.tokens_out,
                    record.cost_usd,
                    record.duration_ms,
                    int(record.cached),
                    record.status,
                    record.error,
                    record.created_at,
                ),
            )
        return record

    def list_llm_runs(self, repo_id: str, *, task_type: str | None = None) -> list[LLMRunRecord]:
        query = """
            SELECT id, repo_id, task_type, provider, model, model_alias, prompt_version,
                   input_hash, cache_key, tokens_in, tokens_out, cost_usd, duration_ms,
                   cached, status, error, created_at
            FROM llm_run
            WHERE repo_id = ?
        """
        params: list[Any] = [repo_id]
        if task_type:
            query += " AND task_type = ?"
            params.append(task_type)
        query += " ORDER BY created_at DESC"
        with self.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [llm_run_from_row(row) for row in rows]

