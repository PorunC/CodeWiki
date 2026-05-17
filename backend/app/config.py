from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMProfileSettings(BaseModel):
    model: str | None = None
    provider_type: str | None = None
    endpoint: str | None = None
    api_key: str | None = None


class LLMSettings(BaseModel):
    mode: str = Field(default="sdk", pattern="^(sdk|proxy)$")
    default: LLMProfileSettings = Field(
        default_factory=lambda: LLMProfileSettings(model="provider/strong-coding-model")
    )
    profiles: dict[str, LLMProfileSettings] = Field(default_factory=dict)
    timeout_seconds: int = 120
    max_retries: int = 3
    cache_enabled: bool = True


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="CODEWIKI_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    app_name: str = "Code Wiki Platform"
    database_url: str = "sqlite+aiosqlite:///./data/codewiki.sqlite3"
    storage_dir: Path = Path("./storage")

    llm: LLMSettings = Field(default_factory=LLMSettings)

    graphrag_context_token_budget: int = 8000
    graphrag_max_source_chunks: int = 20

    wiki_base_language: str = "en"
    wiki_translation_languages: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _upgrade_flat_llm_init_values(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        if "llm" in data:
            return data

        legacy_profile_fields = {
            "model": "model",
            "provider": "provider_type",
            "endpoint": "endpoint",
            "api_key": "api_key",
        }
        task_aliases = {
            "catalog": "catalog",
            "community": "community_summary",
            "page": "page",
            "translation": "translation",
            "qa": "qa",
            "embedding": "embedding",
        }
        llm_payload: dict[str, Any] = {}
        if "llm_mode" in data:
            llm_payload["mode"] = data["llm_mode"]
        for field_name in ("timeout_seconds", "max_retries", "cache_enabled"):
            legacy_key = f"llm_{field_name}"
            if legacy_key in data:
                llm_payload[field_name] = data[legacy_key]

        default_profile = {
            target_key: data[f"llm_{source_key}"]
            for source_key, target_key in legacy_profile_fields.items()
            if f"llm_{source_key}" in data
        }
        if default_profile:
            llm_payload["default"] = default_profile

        profiles: dict[str, dict[str, Any]] = {}
        for legacy_task, task_type in task_aliases.items():
            profile = {
                target_key: data[f"llm_{legacy_task}_{source_key}"]
                for source_key, target_key in legacy_profile_fields.items()
                if f"llm_{legacy_task}_{source_key}" in data
            }
            if profile:
                profiles[task_type] = profile
        if profiles:
            llm_payload["profiles"] = profiles

        if llm_payload:
            data = dict(data)
            data["llm"] = llm_payload
        return data

    @property
    def llm_mode(self) -> str:
        return self.llm.mode

    @property
    def llm_timeout_seconds(self) -> int:
        return self.llm.timeout_seconds

    @property
    def llm_max_retries(self) -> int:
        return self.llm.max_retries

    @property
    def llm_cache_enabled(self) -> bool:
        return self.llm.cache_enabled


@lru_cache
def get_settings() -> Settings:
    return Settings()
