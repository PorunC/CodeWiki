from __future__ import annotations

from typing import Any

from sqlalchemy import ForeignKey, Index, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.models.base import Base, JSONText, RecordMixin


class DocCatalogRecord(Base, RecordMixin):
    __tablename__ = "doc_catalog"
    __table_args__ = (Index("idx_doc_catalog_repo", "repo_id", "language_code", "generated_at"),)
    __record_fields__ = ("id", "repo_id", "language_code", "title", "structure", "generated_at")

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    repo_id: Mapped[str] = mapped_column(Text, ForeignKey("repo.id", ondelete="CASCADE"), nullable=False)
    language_code: Mapped[str] = mapped_column(Text, nullable=False, default="en", server_default=text("'en'"))
    title: Mapped[str] = mapped_column(Text, nullable=False)
    structure: Mapped[dict[str, Any]] = mapped_column(
        "structure_json",
        JSONText(dict),
        nullable=False,
        default=dict,
        server_default=text("'{\"items\":[]}'"),
    )
    generated_at: Mapped[str | None] = mapped_column(Text, server_default=text("CURRENT_TIMESTAMP"))


class DocPageRecord(Base, RecordMixin):
    __tablename__ = "doc_page"
    __table_args__ = (
        Index("idx_doc_page_repo", "repo_id"),
        Index("idx_doc_page_slug_language", "repo_id", "language_code", "slug", unique=True),
    )
    __record_fields__ = (
        "id",
        "repo_id",
        "language_code",
        "slug",
        "title",
        "parent_slug",
        "markdown",
        "source_refs",
        "graph_refs",
        "status",
        "updated_at",
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    repo_id: Mapped[str] = mapped_column(Text, ForeignKey("repo.id", ondelete="CASCADE"), nullable=False)
    language_code: Mapped[str] = mapped_column(Text, nullable=False, default="en", server_default=text("'en'"))
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    parent_slug: Mapped[str | None] = mapped_column(Text)
    markdown: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    source_refs: Mapped[list[dict[str, Any]]] = mapped_column(
        "source_refs_json",
        JSONText(list),
        nullable=False,
        default=list,
        server_default=text("'[]'"),
    )
    graph_refs: Mapped[list[str]] = mapped_column(
        "graph_refs_json",
        JSONText(list),
        nullable=False,
        default=list,
        server_default=text("'[]'"),
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, default="draft", server_default=text("'draft'"))
    updated_at: Mapped[str | None] = mapped_column(Text, server_default=text("CURRENT_TIMESTAMP"))
