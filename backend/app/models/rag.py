from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import ForeignKey, Index, Integer, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.models.base import Base, RecordMixin


class CodeChunkRecord(Base, RecordMixin):
    __tablename__ = "code_chunk"
    __table_args__ = (
        Index("idx_code_chunk_repo", "repo_id"),
        Index("idx_code_chunk_node", "node_id"),
        Index(
            "idx_code_chunk_hash",
            "repo_id",
            "content_hash",
            "file_path",
            "start_line",
            "end_line",
            unique=True,
        ),
    )
    __record_fields__ = (
        "id",
        "repo_id",
        "node_id",
        "file_path",
        "start_line",
        "end_line",
        "content",
        "content_hash",
        "token_count",
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    repo_id: Mapped[str] = mapped_column(Text, ForeignKey("repo.id", ondelete="CASCADE"), nullable=False)
    node_id: Mapped[str | None] = mapped_column(Text, ForeignKey("code_node.id", ondelete="SET NULL"))
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


class CodeChunkEmbeddingRecord(Base, RecordMixin):
    __tablename__ = "code_chunk_embedding"
    __table_args__ = (
        Index("idx_code_chunk_embedding_repo", "repo_id", "model"),
        Index("idx_code_chunk_embedding_chunk_model", "repo_id", "chunk_id", "model", unique=True),
        Index("idx_code_chunk_embedding_vec_row", "vec_table", "vec_rowid", unique=True),
    )
    __allow_unmapped__ = True
    __record_fields__ = (
        "id",
        "repo_id",
        "chunk_id",
        "model",
        "dimensions",
        "embedding",
        "content_hash",
        "created_at",
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    repo_id: Mapped[str] = mapped_column(Text, ForeignKey("repo.id", ondelete="CASCADE"), nullable=False)
    chunk_id: Mapped[str] = mapped_column(Text, ForeignKey("code_chunk.id", ondelete="CASCADE"), nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    vec_table: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    vec_rowid: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str | None] = mapped_column(Text, server_default=text("CURRENT_TIMESTAMP"))
    embedding: list[float]

    def __init__(
        self,
        *,
        id: str,
        repo_id: str,
        chunk_id: str,
        model: str,
        dimensions: int,
        embedding: list[float] | None = None,
        content_hash: str,
        created_at: str | None = None,
        vec_table: str = "",
        vec_rowid: int = 0,
    ) -> None:
        self.id = id
        self.repo_id = repo_id
        self.chunk_id = chunk_id
        self.model = model
        self.dimensions = dimensions
        self.embedding = embedding or []
        self.content_hash = content_hash
        self.created_at = created_at
        self.vec_table = vec_table
        self.vec_rowid = vec_rowid


@dataclass(frozen=True)
class CodeChunkSearchHit:
    chunk: CodeChunkRecord
    score: float
    match_type: str
