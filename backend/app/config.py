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
    llm_model: str = "provider/strong-coding-model"
    llm_provider: str | None = None
    llm_endpoint: str | None = None
    llm_api_key: str | None = None
    llm_catalog_model: str | None = None
    llm_catalog_provider: str | None = None
    llm_catalog_endpoint: str | None = None
    llm_catalog_api_key: str | None = None
    llm_community_model: str | None = None
    llm_community_provider: str | None = None
    llm_community_endpoint: str | None = None
    llm_community_api_key: str | None = None
    llm_page_model: str | None = None
    llm_page_provider: str | None = None
    llm_page_endpoint: str | None = None
    llm_page_api_key: str | None = None
    llm_translation_model: str | None = None
    llm_translation_provider: str | None = None
    llm_translation_endpoint: str | None = None
    llm_translation_api_key: str | None = None
    llm_qa_model: str | None = None
    llm_qa_provider: str | None = None
    llm_qa_endpoint: str | None = None
    llm_qa_api_key: str | None = None
    llm_embedding_model: str | None = None
    llm_embedding_provider: str | None = None
    llm_embedding_endpoint: str | None = None
    llm_embedding_api_key: str | None = None
    llm_timeout_seconds: int = 120
    llm_max_retries: int = 3
    llm_cache_enabled: bool = True

    graphrag_context_token_budget: int = 8000
    graphrag_max_source_chunks: int = 20

    wiki_base_language: str = "en"
    wiki_translation_languages: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
