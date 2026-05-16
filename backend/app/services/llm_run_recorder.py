import json
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from backend.app.database import LLMRunRecord, SQLiteStore
from backend.app.services.llm_gateway import LLMResult


@dataclass(frozen=True)
class RecordedLLMResult:
    result: LLMResult
    run: LLMRunRecord
    cache_hit: bool


async def complete_with_cache(
    store: SQLiteStore,
    repo_id: str,
    *,
    llm: Any,
    task_type: str,
    messages: list[dict[str, str]],
    input_payload: dict[str, Any],
    cache_key: str,
    model_alias: str | None = None,
    prompt_version: str | None = None,
    response_format: str | None = None,
) -> RecordedLLMResult:
    input_hash = payload_hash(input_payload)
    model = llm_model(llm, task_type)
    cached_run = store.get_cached_llm_run(
        repo_id,
        task_type=task_type,
        cache_key=cache_key,
        input_hash=input_hash,
        model=model,
        prompt_version=prompt_version,
    )
    if cached_run is not None:
        result = LLMResult(
            content=cached_run.response_content,
            model=cached_run.model,
            usage=cached_run.response_usage,
            provider=cached_run.provider,
        )
        run = store.record_llm_run(
            repo_id,
            task_type=task_type,
            provider=cached_run.provider,
            model=cached_run.model,
            model_alias=model_alias or cached_run.model_alias or task_type,
            prompt_version=prompt_version,
            input_hash=input_hash,
            cache_key=cache_key,
            tokens_in=cached_run.tokens_in,
            tokens_out=cached_run.tokens_out,
            cost_usd=0.0,
            duration_ms=0,
            response_content=result.content,
            response_usage=result.usage,
            cached=True,
        )
        return RecordedLLMResult(result=result, run=run, cache_hit=True)

    result = await llm.complete(task_type, messages, response_format=response_format)
    run = record_llm_run(
        store,
        repo_id,
        task_type=task_type,
        result=result,
        input_payload=input_payload,
        input_hash=input_hash,
        cache_key=cache_key,
        model_alias=model_alias,
        prompt_version=prompt_version,
    )
    return RecordedLLMResult(result=result, run=run, cache_hit=False)


def record_llm_run(
    store: SQLiteStore,
    repo_id: str,
    *,
    task_type: str,
    result: LLMResult,
    input_payload: dict[str, Any],
    cache_key: str,
    input_hash: str | None = None,
    model_alias: str | None = None,
    prompt_version: str | None = None,
    cached: bool = False,
    status: str = "success",
    error: str | None = None,
) -> LLMRunRecord:
    usage = result.usage or {}
    return store.record_llm_run(
        repo_id,
        task_type=task_type,
        provider=result.provider or model_provider(result.model),
        model=result.model,
        model_alias=model_alias or task_type,
        prompt_version=prompt_version,
        input_hash=input_hash or payload_hash(input_payload),
        cache_key=cache_key,
        tokens_in=token_count(usage, "prompt_tokens", "input_tokens"),
        tokens_out=token_count(usage, "completion_tokens", "output_tokens"),
        response_content=result.content,
        response_usage=usage,
        cached=cached,
        status=status,
        error=error,
    )


def unique_cache_key(*parts: object) -> str:
    return stable_cache_key(*parts)


def stable_cache_key(*parts: object) -> str:
    return ":".join(str(part) for part in parts)


def payload_hash(payload: dict[str, Any]) -> str:
    return sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def model_provider(model: str) -> str | None:
    return model.split("/", 1)[0] if "/" in model else None


def llm_model(llm: Any, task_type: str) -> str | None:
    router = getattr(llm, "router", None)
    profile_for = getattr(router, "profile_for", None)
    if profile_for is None:
        return None
    profile = profile_for(task_type)
    return getattr(profile, "model", None)


def token_count(usage: dict[str, Any], *keys: str) -> int:
    for key in keys:
        value = usage.get(key)
        if value is not None:
            return int(value or 0)
    return 0
