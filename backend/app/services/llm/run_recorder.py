from dataclasses import dataclass
from hashlib import sha256
from inspect import signature
import json
import re
from typing import Any

from backend.app.database import LLMRunRecord, CodeWikiStore
from backend.app.services.llm.gateway import LLMResult

ERROR_MESSAGE_LIMIT = 1600


class LLMCallError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        task_type: str,
        run_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.task_type = task_type
        self.run_id = run_id


@dataclass(frozen=True)
class RecordedLLMResult:
    result: LLMResult
    run: LLMRunRecord
    cache_hit: bool


async def complete_with_cache(
    store: CodeWikiStore,
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
    provider_user_id: str | None = None,
) -> RecordedLLMResult:
    input_hash = payload_hash(input_payload)
    model = llm_model(llm, task_type)
    provider = llm_provider(llm, task_type)
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

    try:
        result = await _complete_llm(
            llm,
            task_type,
            messages,
            response_format=response_format,
            provider_user_id=provider_user_id,
        )
    except Exception as exc:
        error = sanitized_llm_error(exc)
        run = record_failed_llm_run(
            store,
            repo_id,
            task_type=task_type,
            input_payload=input_payload,
            input_hash=input_hash,
            cache_key=cache_key,
            model=model,
            provider=provider,
            model_alias=model_alias,
            prompt_version=prompt_version,
            error=error,
        )
        raise LLMCallError(error, task_type=task_type, run_id=run.id) from exc
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


async def _complete_llm(
    llm: Any,
    task_type: str,
    messages: list[dict[str, str]],
    *,
    response_format: str | None,
    provider_user_id: str | None,
) -> LLMResult:
    complete = llm.complete
    parameters = signature(complete).parameters
    if "provider_user_id" in parameters:
        return await complete(
            task_type,
            messages,
            response_format=response_format,
            provider_user_id=provider_user_id,
        )
    return await complete(task_type, messages, response_format=response_format)


def record_llm_run(
    store: CodeWikiStore,
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
    usage = normalize_usage(result.usage or {})
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


def record_failed_llm_run(
    store: CodeWikiStore,
    repo_id: str,
    *,
    task_type: str,
    input_payload: dict[str, Any],
    cache_key: str,
    error: str,
    input_hash: str | None = None,
    model: str | None = None,
    provider: str | None = None,
    model_alias: str | None = None,
    prompt_version: str | None = None,
) -> LLMRunRecord:
    recorded_model = model or model_alias or task_type
    return store.record_llm_run(
        repo_id,
        task_type=task_type,
        provider=provider or model_provider(recorded_model),
        model=recorded_model,
        model_alias=model_alias or task_type,
        prompt_version=prompt_version,
        input_hash=input_hash or payload_hash(input_payload),
        cache_key=cache_key,
        tokens_in=0,
        tokens_out=0,
        response_content="",
        response_usage={},
        cached=False,
        status="error",
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
    return _llm_profile_value(llm, task_type, "model")


def llm_provider(llm: Any, task_type: str) -> str | None:
    return _llm_profile_value(llm, task_type, "provider_type")


def _llm_profile_value(llm: Any, task_type: str, name: str) -> str | None:
    router = getattr(llm, "router", None)
    profile_for = getattr(router, "profile_for", None)
    if profile_for is None:
        return None
    profile = profile_for(task_type)
    return getattr(profile, name, None)


def token_count(usage: dict[str, Any], *keys: str) -> int:
    for key in keys:
        value = usage.get(key)
        if value is not None:
            return int(value or 0)
    return 0


def normalize_usage(usage: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(usage)
    prompt_tokens = token_count(
        normalized,
        "prompt_tokens",
        "input_tokens",
        "prompt_eval_count",
    )
    completion_tokens = token_count(
        normalized,
        "completion_tokens",
        "output_tokens",
        "eval_count",
    )
    cache_hit_tokens = _cache_token_count(
        normalized,
        "prompt_cache_hit_tokens",
        "cache_read_input_tokens",
        "cached_input_tokens",
        "input_cached_tokens",
    )
    cache_miss_tokens = _cache_token_count(
        normalized,
        "prompt_cache_miss_tokens",
        "cache_creation_input_tokens",
        "uncached_input_tokens",
        "input_uncached_tokens",
    )
    if cache_hit_tokens is not None:
        normalized["prompt_cache_hit_tokens"] = cache_hit_tokens
    if cache_miss_tokens is None and cache_hit_tokens is not None and prompt_tokens:
        cache_miss_tokens = max(0, prompt_tokens - cache_hit_tokens)
    if cache_miss_tokens is not None:
        normalized["prompt_cache_miss_tokens"] = cache_miss_tokens
    cache_total = (cache_hit_tokens or 0) + (cache_miss_tokens or 0)
    if cache_total > 0:
        normalized["prompt_cache_hit_ratio"] = (cache_hit_tokens or 0) / cache_total
    if prompt_tokens and "prompt_tokens" not in normalized:
        normalized["prompt_tokens"] = prompt_tokens
    if completion_tokens and "completion_tokens" not in normalized:
        normalized["completion_tokens"] = completion_tokens
    return normalized


def _cache_token_count(usage: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = usage.get(key)
        if value is not None:
            return int(value or 0)
    for nested_key in ("prompt_tokens_details", "input_tokens_details", "usage_details"):
        nested = usage.get(nested_key)
        if isinstance(nested, dict):
            nested_value = _cache_token_count(nested, *keys)
            if nested_value is not None:
                return nested_value
    return None


def sanitized_llm_error(exc: Exception) -> str:
    raw = str(exc) or exc.__class__.__name__
    redacted = _redact_secrets(raw.replace("\x00", ""))
    if len(redacted) > ERROR_MESSAGE_LIMIT:
        redacted = f"{redacted[:ERROR_MESSAGE_LIMIT]}..."
    return f"{exc.__class__.__name__}: {redacted}"


def _redact_secrets(message: str) -> str:
    patterns = [
        r"sk-[A-Za-z0-9_-]{8,}",
        r"(?i)(api[_-]?key\s*[:=]\s*)\S+",
        r"(?i)(authorization\s*[:=]\s*bearer\s+)\S+",
    ]
    redacted = message
    for pattern in patterns:
        redacted = re.sub(pattern, _redaction_replacement, redacted)
    return redacted


def _redaction_replacement(match: re.Match[str]) -> str:
    if match.lastindex:
        return f"{match.group(1)}[REDACTED]"
    return "[REDACTED]"
