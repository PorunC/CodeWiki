from __future__ import annotations

from typing import Any

from sqlalchemy import Float, ForeignKey, Index, Integer, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.models.base import Base, JSONText, RecordMixin


class CodeNodeRecord(Base, RecordMixin):
    __tablename__ = "code_node"
    __table_args__ = (
        Index("idx_code_node_repo", "repo_id"),
        Index("idx_code_node_type", "repo_id", "type"),
        Index("idx_code_node_file", "repo_id", "file_path"),
    )
    __record_fields__ = (
        "id",
        "repo_id",
        "type",
        "name",
        "file_path",
        "start_line",
        "end_line",
        "language",
        "symbol_id",
        "summary",
        "hash",
        "metadata_json",
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    repo_id: Mapped[str] = mapped_column(Text, ForeignKey("repo.id", ondelete="CASCADE"), nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    start_line: Mapped[int | None] = mapped_column(Integer)
    end_line: Mapped[int | None] = mapped_column(Integer)
    language: Mapped[str | None] = mapped_column(Text)
    symbol_id: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    hash: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSONText(dict),
        nullable=False,
        default=dict,
        server_default="{}",
    )


class CodeEdgeRecord(Base, RecordMixin):
    __tablename__ = "code_edge"
    __table_args__ = (
        Index("idx_code_edge_repo", "repo_id"),
        Index("idx_code_edge_source", "source_id"),
        Index("idx_code_edge_target", "target_id"),
    )
    __record_fields__ = (
        "id",
        "repo_id",
        "source_id",
        "target_id",
        "type",
        "confidence",
        "weight",
        "is_inferred",
        "metadata_json",
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    repo_id: Mapped[str] = mapped_column(Text, ForeignKey("repo.id", ondelete="CASCADE"), nullable=False)
    source_id: Mapped[str] = mapped_column(Text, ForeignKey("code_node.id", ondelete="CASCADE"), nullable=False)
    target_id: Mapped[str] = mapped_column(Text, ForeignKey("code_node.id", ondelete="CASCADE"), nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0, server_default="1.0")
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0, server_default="1.0")
    is_inferred: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="0")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSONText(dict),
        nullable=False,
        default=dict,
        server_default="{}",
    )


class GraphCommunityRecord(Base, RecordMixin):
    __tablename__ = "graph_community"
    __table_args__ = (
        Index("idx_graph_community_repo", "repo_id"),
        Index("idx_graph_community_level", "repo_id", "level"),
        Index("idx_graph_community_parent", "repo_id", "parent_id"),
    )
    __record_fields__ = (
        "id",
        "repo_id",
        "name",
        "level",
        "parent_id",
        "rank",
        "node_ids",
        "summary",
        "summary_hash",
        "created_at",
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    repo_id: Mapped[str] = mapped_column(Text, ForeignKey("repo.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    parent_id: Mapped[str | None] = mapped_column(Text)
    rank: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    node_ids: Mapped[list[str]] = mapped_column(
        "node_ids_json",
        JSONText(list),
        nullable=False,
        default=list,
        server_default="[]",
    )
    summary: Mapped[str | None] = mapped_column(Text)
    summary_hash: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str | None] = mapped_column(Text, server_default=text("CURRENT_TIMESTAMP"))


class GraphCommunityEdgeRecord(Base, RecordMixin):
    __tablename__ = "graph_community_edge"
    __table_args__ = (
        Index("idx_graph_community_edge_repo", "repo_id"),
        Index("idx_graph_community_edge_source", "source_community_id"),
        Index("idx_graph_community_edge_target", "target_community_id"),
        Index("idx_graph_community_edge_type", "repo_id", "type"),
    )
    __record_fields__ = (
        "id",
        "repo_id",
        "source_community_id",
        "target_community_id",
        "type",
        "weight",
        "confidence",
        "reason",
        "evidence_edge_ids",
        "created_at",
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    repo_id: Mapped[str] = mapped_column(Text, ForeignKey("repo.id", ondelete="CASCADE"), nullable=False)
    source_community_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("graph_community.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_community_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("graph_community.id", ondelete="CASCADE"),
        nullable=False,
    )
    type: Mapped[str] = mapped_column(Text, nullable=False)
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0, server_default="1.0")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0, server_default="1.0")
    reason: Mapped[str | None] = mapped_column(Text)
    evidence_edge_ids: Mapped[list[str]] = mapped_column(
        "evidence_edge_ids_json",
        JSONText(list),
        nullable=False,
        default=list,
        server_default="[]",
    )
    created_at: Mapped[str | None] = mapped_column(Text, server_default=text("CURRENT_TIMESTAMP"))
