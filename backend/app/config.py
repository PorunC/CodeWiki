from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="CODEWIKI_",
        extra="ignore",
    )

    app_name: str = "Code Wiki Platform"
    database_url: str = "sqlite+aiosqlite:///./data/codewiki.sqlite3"
    storage_dir: Path = Path("./storage")

    llm_mode: str = Field(default="sdk", pattern="^(sdk|proxy)$")
    llm_base_url: str | None = None
    litellm_proxy_base_url: str | None = None
    llm_default_model: str = "provider/strong-coding-model"
    llm_embedding_model: str = "provider/embedding-model"
    llm_api_key: str | None = None
    llm_timeout_seconds: int = 120
    llm_max_retries: int = 3
    llm_cache_enabled: bool = True

    graphrag_context_token_budget: int = 8000
    graphrag_max_source_chunks: int = 20


@lru_cache
def get_settings() -> Settings:
    return Settings()
