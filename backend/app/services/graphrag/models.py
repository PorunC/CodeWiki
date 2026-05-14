from dataclasses import dataclass, field

from backend.app.database import CodeChunkRecord


@dataclass(frozen=True)
class GraphRAGBuildResult:
    repo_id: str
    status: str
    chunk_count: int
    embedding_count: int = 0
    embedding_model: str | None = None


@dataclass(frozen=True)
class RetrievalTrace:
    repo_id: str
    query: str
    max_hops: int
    trace_id: str
    seed_nodes: list[dict[str, object]] = field(default_factory=list)
    expanded_nodes: list[dict[str, object]] = field(default_factory=list)
    source_chunks: list[dict[str, object]] = field(default_factory=list)
    related_edges: list[dict[str, object]] = field(default_factory=list)
    community_summaries: list[dict[str, object]] = field(default_factory=list)
    context_pack: dict[str, object] = field(default_factory=dict)


@dataclass
class NodeHit:
    node_id: str
    score: float
    reasons: set[str] = field(default_factory=set)


@dataclass
class ChunkHit:
    chunk: CodeChunkRecord
    score: float
    reasons: set[str] = field(default_factory=set)
    score_components: dict[str, float] = field(default_factory=dict)
