import json
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
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO llm_run (
                  id, repo_id, task_type, provider, model, model_alias, prompt_version,
                  input_hash, cache_key, tokens_in, tokens_out, cost_usd, duration_ms,
                  response_content, response_usage_json, cached, status, error, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    record.response_content,
                    json.dumps(record.response_usage, sort_keys=True),
                    int(record.cached),
                    record.status,
                    record.error,
                    record.created_at,
                ),
            )
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
        query = """
            SELECT id, repo_id, task_type, provider, model, model_alias, prompt_version,
                   input_hash, cache_key, tokens_in, tokens_out, cost_usd, duration_ms,
                   response_content, response_usage_json, cached, status, error, created_at
            FROM llm_run
            WHERE repo_id = ?
              AND task_type = ?
              AND cache_key = ?
              AND input_hash = ?
              AND status = 'success'
              AND response_content <> ''
        """
        params: list[Any] = [repo_id, task_type, cache_key, input_hash]
        if model is not None:
            query += " AND model = ?"
            params.append(model)
        if prompt_version is not None:
            query += " AND prompt_version = ?"
            params.append(prompt_version)
        query += " ORDER BY created_at DESC LIMIT 1"
        with self.connect() as connection:
            row = connection.execute(query, params).fetchone()
        return llm_run_from_row(row) if row is not None else None

    def update_llm_run_status(
        self,
        run_id: str,
        *,
        status: str,
        error: str | None = None,
    ) -> LLMRunRecord | None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE llm_run SET status = ?, error = ? WHERE id = ?",
                (status, error, run_id),
            )
            row = connection.execute(
                """
                SELECT id, repo_id, task_type, provider, model, model_alias, prompt_version,
                       input_hash, cache_key, tokens_in, tokens_out, cost_usd, duration_ms,
                       response_content, response_usage_json, cached, status, error, created_at
                FROM llm_run
                WHERE id = ?
                """,
                (run_id,),
            ).fetchone()
        return llm_run_from_row(row) if row is not None else None

    def list_llm_runs(self, repo_id: str, *, task_type: str | None = None) -> list[LLMRunRecord]:
        query = """
            SELECT id, repo_id, task_type, provider, model, model_alias, prompt_version,
                   input_hash, cache_key, tokens_in, tokens_out, cost_usd, duration_ms,
                   response_content, response_usage_json, cached, status, error, created_at
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
