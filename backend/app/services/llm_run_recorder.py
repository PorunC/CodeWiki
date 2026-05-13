import json
import uuid
from hashlib import sha256
from typing import Any

from backend.app.database import LLMRunRecord, SQLiteStore
from backend.app.services.llm_gateway import LLMResult


def record_llm_run(
    store: SQLiteStore,
    repo_id: str,
    *,
    task_type: str,
    result: LLMResult,
    input_payload: dict[str, Any],
    cache_key: str,
    model_alias: str | None = None,
    prompt_version: str | None = None,
    status: str = "success",
    error: str | None = None,
) -> LLMRunRecord:
    usage = result.usage or {}
    return store.record_llm_run(
        repo_id,
        task_type=task_type,
        provider=model_provider(result.model),
        model=result.model,
        model_alias=model_alias or task_type,
        prompt_version=prompt_version,
        input_hash=payload_hash(input_payload),
        cache_key=cache_key,
        tokens_in=token_count(usage, "prompt_tokens", "input_tokens"),
        tokens_out=token_count(usage, "completion_tokens", "output_tokens"),
        status=status,
        error=error,
    )


def unique_cache_key(*parts: object) -> str:
    return ":".join([*(str(part) for part in parts), uuid.uuid4().hex])


def payload_hash(payload: dict[str, Any]) -> str:
    return sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def model_provider(model: str) -> str | None:
    return model.split("/", 1)[0] if "/" in model else None


def token_count(usage: dict[str, Any], *keys: str) -> int:
    for key in keys:
        value = usage.get(key)
        if value is not None:
            return int(value or 0)
    return 0
