from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AnalysisRunRecord:
    id: str
    repo_id: str
    status: str
    started_at: str | None
    finished_at: str | None
    error: str | None
    stats: dict[str, Any]


@dataclass(frozen=True)
class CodeChunkRecord:
    id: str
    repo_id: str
    node_id: str | None
    file_path: str
    start_line: int
    end_line: int
    content: str
    content_hash: str
    token_count: int


@dataclass(frozen=True)
class CodeChunkSearchHit:
    chunk: CodeChunkRecord
    score: float
    match_type: str


@dataclass(frozen=True)
class CodeChunkEmbeddingRecord:
    id: str
    repo_id: str
    chunk_id: str
    model: str
    dimensions: int
    embedding: list[float]
    content_hash: str
    created_at: str | None


@dataclass(frozen=True)
class GraphCommunityRecord:
    id: str
    repo_id: str
    name: str
    level: int
    node_ids: list[str]
    summary: str | None
    summary_hash: str | None
    created_at: str | None


@dataclass(frozen=True)
class DocCatalogRecord:
    id: str
    repo_id: str
    title: str
    structure: dict[str, Any]
    generated_at: str | None


@dataclass(frozen=True)
class DocPageRecord:
    id: str
    repo_id: str
    slug: str
    title: str
    parent_slug: str | None
    markdown: str
    source_refs: list[dict[str, Any]]
    graph_refs: list[str]
    status: str
    updated_at: str | None


@dataclass(frozen=True)
class LLMRunRecord:
    id: str
    repo_id: str
    task_type: str
    provider: str | None
    model: str
    model_alias: str | None
    prompt_version: str | None
    input_hash: str
    cache_key: str
    tokens_in: int
    tokens_out: int
    cost_usd: float | None
    duration_ms: int | None
    cached: bool
    status: str
    error: str | None
    created_at: str | None
