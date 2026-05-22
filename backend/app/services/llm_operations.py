from dataclasses import dataclass, field
from typing import Any

from backend.app.database import CodeWikiStore
from backend.app.services.llm_run_recorder import RecordedLLMResult, complete_with_cache


@dataclass(frozen=True)
class LLMOperation:
    task_type: str
    messages: list[dict[str, str]]
    input_payload: dict[str, Any]
    cache_namespace: str
    cache_parts: tuple[object, ...] = field(default_factory=tuple)
    model_alias: str | None = None
    prompt_version: str | None = None
    response_format: str | None = None

    @property
    def cache_key(self) -> str:
        return ":".join(str(part) for part in (self.cache_namespace, *self.cache_parts))


class CachedLLMService:
    def __init__(self, *, store: CodeWikiStore, llm: Any) -> None:
        self.store = store
        self.llm = llm

    async def complete(self, repo_id: str, operation: LLMOperation) -> RecordedLLMResult:
        return await complete_with_cache(
            self.store,
            repo_id,
            llm=self.llm,
            task_type=operation.task_type,
            messages=operation.messages,
            input_payload=operation.input_payload,
            cache_key=operation.cache_key,
            model_alias=operation.model_alias,
            prompt_version=operation.prompt_version,
            response_format=operation.response_format,
        )
