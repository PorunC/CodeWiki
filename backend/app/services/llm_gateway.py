from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from backend.app.config import Settings
from backend.app.services.model_router import ModelRouter


@dataclass(frozen=True)
class LLMResult:
    content: str
    model: str
    usage: dict[str, Any]


@dataclass(frozen=True)
class LLMDelta:
    content: str


class LLMGateway:
    """LiteLLM-first gateway.

    Business services depend on this class instead of importing provider SDKs directly.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.router = ModelRouter(settings)

    async def complete(
        self,
        task_type: str,
        messages: list[dict[str, str]],
        *,
        response_format: str | None = None,
    ) -> LLMResult:
        from litellm import acompletion

        profile = self.router.profile_for(task_type)
        kwargs: dict[str, Any] = {
            "model": profile.model,
            "messages": messages,
            "temperature": profile.temperature,
            "timeout": self.settings.llm_timeout_seconds,
        }
        if profile.max_tokens:
            kwargs["max_tokens"] = profile.max_tokens
        if response_format:
            kwargs["response_format"] = {"type": response_format}
        if self.settings.llm_mode == "proxy" and self.settings.litellm_proxy_base_url:
            kwargs["api_base"] = self.settings.litellm_proxy_base_url
        if self.settings.llm_api_key:
            kwargs["api_key"] = self.settings.llm_api_key

        response = await acompletion(**kwargs)
        choice = response.choices[0]
        content = choice.message.content or ""
        usage_obj = getattr(response, "usage", None)
        if hasattr(usage_obj, "model_dump"):
            usage = usage_obj.model_dump()
        elif isinstance(usage_obj, dict):
            usage = usage_obj
        else:
            usage = {}
        return LLMResult(content=content, model=profile.model, usage=usage)

    async def stream(self, task_type: str, messages: list[dict[str, str]]) -> AsyncIterator[LLMDelta]:
        from litellm import acompletion

        profile = self.router.profile_for(task_type)
        kwargs: dict[str, Any] = {
            "model": profile.model,
            "messages": messages,
            "temperature": profile.temperature,
            "stream": True,
            "timeout": self.settings.llm_timeout_seconds,
        }
        if self.settings.llm_mode == "proxy" and self.settings.litellm_proxy_base_url:
            kwargs["api_base"] = self.settings.litellm_proxy_base_url
        if self.settings.llm_api_key:
            kwargs["api_key"] = self.settings.llm_api_key
        response = await acompletion(**kwargs)
        async for chunk in response:
            delta = chunk.choices[0].delta
            content = getattr(delta, "content", None)
            if content:
                yield LLMDelta(content=content)

    async def embed(self, texts: list[str], *, task_type: str = "embedding") -> list[list[float]]:
        from litellm import aembedding

        profile = self.router.profile_for(task_type)
        kwargs: dict[str, Any] = {"model": profile.model, "input": texts}
        if self.settings.llm_mode == "proxy" and self.settings.litellm_proxy_base_url:
            kwargs["api_base"] = self.settings.litellm_proxy_base_url
        if self.settings.llm_api_key:
            kwargs["api_key"] = self.settings.llm_api_key
        response = await aembedding(**kwargs)
        return [
            item["embedding"] if isinstance(item, dict) else item.embedding
            for item in response.data
        ]
