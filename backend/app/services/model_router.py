from dataclasses import dataclass, field

from backend.app.config import Settings


@dataclass(frozen=True)
class ModelProfile:
    task_type: str
    model: str
    provider_type: str | None = None
    endpoint: str | None = None
    api_key: str | None = None
    temperature: float = 0.1
    max_tokens: int | None = None
    stream: bool = False
    fallback_models: list[str] = field(default_factory=list)


class ModelRouter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def profile_for(self, task_type: str) -> ModelProfile:
        if task_type == "embedding":
            return self._profile(
                task_type,
                model=self.settings.llm_embedding_model,
                endpoint=self.settings.llm_embedding_endpoint,
                api_key=self.settings.llm_embedding_api_key,
                provider_type=self.settings.llm_embedding_provider,
            )
        if task_type == "catalog":
            return self._profile(
                task_type,
                model=self.settings.llm_catalog_model,
                endpoint=self.settings.llm_catalog_endpoint,
                api_key=self.settings.llm_catalog_api_key,
                provider_type=self.settings.llm_catalog_provider,
                max_tokens=4096,
            )
        if task_type in {"community_summary", "cluster"}:
            return self._profile(
                task_type,
                model=self.settings.llm_community_model,
                endpoint=self.settings.llm_community_endpoint,
                api_key=self.settings.llm_community_api_key,
                provider_type=self.settings.llm_community_provider,
                max_tokens=4096,
            )
        if task_type == "page":
            return self._profile(
                task_type,
                model=self.settings.llm_page_model,
                endpoint=self.settings.llm_page_endpoint,
                api_key=self.settings.llm_page_api_key,
                provider_type=self.settings.llm_page_provider,
                max_tokens=12000,
            )
        if task_type == "translation":
            return self._profile(
                task_type,
                model=self.settings.llm_translation_model,
                endpoint=self.settings.llm_translation_endpoint,
                api_key=self.settings.llm_translation_api_key,
                provider_type=self.settings.llm_translation_provider,
                max_tokens=12000,
            )
        if task_type == "qa":
            return self._profile(
                task_type,
                model=self.settings.llm_qa_model,
                endpoint=self.settings.llm_qa_endpoint,
                api_key=self.settings.llm_qa_api_key,
                provider_type=self.settings.llm_qa_provider,
                stream=True,
            )
        raise ValueError(f"Unsupported LLM task type: {task_type}")

    def _profile(
        self,
        task_type: str,
        *,
        model: str | None,
        endpoint: str | None = None,
        api_key: str | None = None,
        provider_type: str | None = None,
        temperature: float = 0.1,
        max_tokens: int | None = None,
        stream: bool = False,
    ) -> ModelProfile:
        return ModelProfile(
            task_type=task_type,
            model=self._value(model, self.settings.llm_model) or self.settings.llm_model,
            provider_type=self._value(provider_type, self.settings.llm_provider),
            endpoint=self._value(endpoint, self.settings.llm_endpoint),
            api_key=self._value(api_key, self.settings.llm_api_key),
            temperature=temperature,
            max_tokens=max_tokens,
            stream=stream,
        )

    def default_profile(self) -> ModelProfile:
        return self._profile("default", model=self.settings.llm_model)

    @staticmethod
    def _value(*values: str | None) -> str | None:
        for value in values:
            if value is None:
                continue
            stripped = value.strip()
            if stripped:
                return stripped
        return None
