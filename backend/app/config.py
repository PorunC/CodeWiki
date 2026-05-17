from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field
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


@lru_cache
def get_settings() -> Settings:
    return Settings()
