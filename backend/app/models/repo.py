from __future__ import annotations

from typing import Any

from sqlalchemy import Float, ForeignKey, Index, Integer, Text, false, text
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.models.base import Base, JSONText, RecordMixin


class RepoRecord(Base, RecordMixin):
    __tablename__ = "repo"
    __record_fields__ = (
        "id",
        "name",
        "path",
        "source_type",
        "git_url",
        "commit_hash",
        "created_at",
        "updated_at",
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(Text, nullable=False, default="local", server_default=text("'local'"))
    git_url: Mapped[str | None] = mapped_column(Text)
    commit_hash: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str | None] = mapped_column(Text, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[str | None] = mapped_column(Text, server_default=text("CURRENT_TIMESTAMP"))


class AnalysisRunRecord(Base, RecordMixin):
    __tablename__ = "analysis_run"
    __table_args__ = (Index("idx_analysis_run_repo", "repo_id", "started_at"),)
    __record_fields__ = ("id", "repo_id", "status", "started_at", "finished_at", "error", "stats")

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    repo_id: Mapped[str] = mapped_column(Text, ForeignKey("repo.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending", server_default=text("'pending'"))
    started_at: Mapped[str | None] = mapped_column(Text)
    finished_at: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    stats: Mapped[dict[str, Any]] = mapped_column(
        "stats_json",
        JSONText(dict),
        nullable=False,
        default=dict,
        server_default=text("'{}'"),
    )


class LLMRunRecord(Base, RecordMixin):
    __tablename__ = "llm_run"
    __table_args__ = (
        Index("idx_llm_run_task", "repo_id", "task_type", "cache_key"),
        Index(
            "idx_llm_run_cache",
            "repo_id",
            "task_type",
            "cache_key",
            "input_hash",
            "model",
            "prompt_version",
        ),
        Index("idx_llm_run_created", "repo_id", "created_at"),
    )
    __record_fields__ = (
        "id",
        "repo_id",
        "task_type",
        "provider",
        "model",
        "model_alias",
        "prompt_version",
        "input_hash",
        "cache_key",
        "tokens_in",
        "tokens_out",
        "cost_usd",
        "duration_ms",
        "response_content",
        "response_usage",
        "cached",
        "status",
        "error",
        "created_at",
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    repo_id: Mapped[str] = mapped_column(Text, ForeignKey("repo.id", ondelete="CASCADE"), nullable=False)
    task_type: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    model_alias: Mapped[str | None] = mapped_column(Text)
    prompt_version: Mapped[str | None] = mapped_column(Text)
    input_hash: Mapped[str] = mapped_column(Text, nullable=False)
    cache_key: Mapped[str] = mapped_column(Text, nullable=False)
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    cost_usd: Mapped[float | None] = mapped_column(Float)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    response_content: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    response_usage: Mapped[dict[str, Any]] = mapped_column(
        "response_usage_json",
        JSONText(dict),
        nullable=False,
        default=dict,
        server_default=text("'{}'"),
    )
    cached: Mapped[bool] = mapped_column(nullable=False, default=False, server_default=false())
    status: Mapped[str] = mapped_column(Text, nullable=False, default="success", server_default=text("'success'"))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str | None] = mapped_column(Text, server_default=text("CURRENT_TIMESTAMP"))
