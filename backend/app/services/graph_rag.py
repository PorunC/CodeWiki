from dataclasses import dataclass, field


@dataclass(frozen=True)
class RetrievalTrace:
    query: str
    seed_nodes: list[dict[str, object]] = field(default_factory=list)
    expanded_nodes: list[dict[str, object]] = field(default_factory=list)
    source_chunks: list[dict[str, object]] = field(default_factory=list)
    community_summaries: list[dict[str, object]] = field(default_factory=list)


class GraphRAGRetriever:
    async def retrieve(self, repo_id: str, query: str, *, max_hops: int = 2) -> RetrievalTrace:
        return RetrievalTrace(query=query)

