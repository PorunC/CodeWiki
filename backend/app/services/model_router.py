from dataclasses import dataclass, field

from backend.app.config import LLMProfileSettings, Settings


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


@dataclass(frozen=True)
class TaskRoutingDefaults:
    max_tokens: int | None = None
    stream: bool = False
    profile_key: str | None = None


TASK_ROUTING_DEFAULTS: dict[str, TaskRoutingDefaults] = {
    "catalog": TaskRoutingDefaults(max_tokens=4096),
    "community_summary": TaskRoutingDefaults(max_tokens=4096),
    "cluster": TaskRoutingDefaults(max_tokens=4096, profile_key="community_summary"),
    "page": TaskRoutingDefaults(max_tokens=12000),
    "translation": TaskRoutingDefaults(max_tokens=12000),
    "qa": TaskRoutingDefaults(stream=True),
    "embedding": TaskRoutingDefaults(),
}


class ModelRouter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def profile_for(self, task_type: str) -> ModelProfile:
        defaults = TASK_ROUTING_DEFAULTS.get(task_type)
        if defaults is None:
            raise ValueError(f"Unsupported LLM task type: {task_type}")
        profile_key = defaults.profile_key or task_type
        profile_config = self._configured_profile(profile_key)
        return self._profile(
            task_type,
            profile_config,
            max_tokens=defaults.max_tokens,
            stream=defaults.stream,
        )

    def default_profile(self) -> ModelProfile:
        return self._profile("default", LLMProfileSettings())

    def _profile(
        self,
        task_type: str,
        profile_config: LLMProfileSettings,
        *,
        temperature: float = 0.1,
        max_tokens: int | None = None,
        stream: bool = False,
    ) -> ModelProfile:
        default = self.settings.llm.default
        return ModelProfile(
            task_type=task_type,
            model=self._value(profile_config.model, default.model) or "provider/strong-coding-model",
            provider_type=self._value(profile_config.provider_type, default.provider_type),
            endpoint=self._value(profile_config.endpoint, default.endpoint),
            api_key=self._value(profile_config.api_key, default.api_key),
            temperature=temperature,
            max_tokens=max_tokens,
            stream=stream,
        )

    def _configured_profile(self, profile_key: str) -> LLMProfileSettings:
        for key, profile in self.settings.llm.profiles.items():
            if key.strip().lower() == profile_key:
                return profile
        return LLMProfileSettings()

    @staticmethod
    def _value(*values: str | None) -> str | None:
        for value in values:
            if value is None:
                continue
            stripped = value.strip()
            if stripped:
                return stripped
        return None
