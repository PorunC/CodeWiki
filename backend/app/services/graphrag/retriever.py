from backend.app.config import Settings, get_settings
from backend.app.database import CodeChunkRecord, SQLiteStore, get_store
from backend.app.services.graph import CodeGraphNode
from backend.app.services.graphrag.constants import (
    DEFAULT_CONTEXT_TOKENS,
    DEFAULT_MAX_SOURCE_CHUNKS,
    MAX_SEED_NODES,
)
from backend.app.services.graphrag.context import (
    chunk_payload,
    community_edge_payloads,
    community_summaries,
    context_pack,
    edge_payload,
    node_payload,
    select_source_chunks,
)
from backend.app.services.graphrag.expansion import expand, related_edges
from backend.app.services.graphrag.indexer import build_index as build_graphrag_index
from backend.app.services.graphrag.models import GraphRAGBuildResult, RetrievalTrace
from backend.app.services.graphrag.search import (
    add_overview_fallback_seeds,
    merge_chunk_hits_into_seeds,
    search_fts,
    search_vectors,
    seed_from_symbols,
)
from backend.app.services.graphrag.utils import stable_id
from backend.app.services.llm_gateway import LLMGateway


class GraphRAGRetriever:
    def __init__(
        self,
        *,
        store: SQLiteStore | None = None,
        llm: LLMGateway | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.store = store or get_store()
        self.settings = settings or get_settings()
        self.llm = llm

    async def build_index(
        self,
        repo_id: str,
        *,
        include_embeddings: bool = False,
    ) -> GraphRAGBuildResult:
        return await build_graphrag_index(
            self.store,
            repo_id,
            include_embeddings=include_embeddings,
            llm=self._llm() if include_embeddings else self.llm,
            settings=self.settings,
        )

    async def retrieve(
        self,
        repo_id: str,
        query: str,
        *,
        max_hops: int = 2,
        include_embeddings: bool = False,
    ) -> RetrievalTrace:
        repo = self.store.get_repo(repo_id)
        if repo is None:
            raise ValueError(f"Repository not found: {repo_id}")

        nodes, edges = self.store.get_graph(repo_id)
        if not nodes:
            raise ValueError("Run analysis before GraphRAG retrieval.")

        query = query.strip() or "repository overview"
        max_hops = max(0, min(max_hops, 4))

        chunks = self.store.list_code_chunks(repo_id)
        if not chunks:
            await self.build_index(repo_id, include_embeddings=False)
            chunks = self.store.list_code_chunks(repo_id)

        node_by_id = {node.id: node for node in nodes}
        seed_hits = seed_from_symbols(query, nodes, store=self.store, repo_id=repo_id)
        fts_hits = search_fts(self.store, repo_id, query, limit=self._max_source_chunks())
        vector_hits = (
            await search_vectors(
                self.store,
                self._llm(),
                repo_id,
                query,
                chunks,
                limit=self._max_source_chunks(),
            )
            if include_embeddings
            else []
        )
        merge_chunk_hits_into_seeds(seed_hits, fts_hits + vector_hits, node_by_id)

        if not seed_hits:
            add_overview_fallback_seeds(seed_hits, nodes)

        seed_hits = dict(
            sorted(seed_hits.items(), key=lambda item: item[1].score, reverse=True)[:MAX_SEED_NODES]
        )
        selected_ids, hops, scores = expand(seed_hits, edges, max_hops=max_hops)
        graph_edges = related_edges(edges, selected_ids)
        source_chunks = select_source_chunks(
            self.store,
            repo_id=repo_id,
            selected_ids=selected_ids,
            seed_ids=set(seed_hits),
            nodes=nodes,
            edges=edges,
            hops=hops,
            fts_hits=fts_hits,
            vector_hits=vector_hits,
            max_source_chunks=self._max_source_chunks(),
            context_token_budget=self._context_token_budget(),
        )
        communities = community_summaries(self.store, repo_id, selected_ids)
        selected_community_ids = {str(community["id"]) for community in communities}
        community_edges = community_edge_payloads(self.store, repo_id, selected_community_ids)

        seed_nodes = [
            node_payload(node_by_id[node_id], hit.score, sorted(hit.reasons), hop=0)
            for node_id, hit in seed_hits.items()
            if node_id in node_by_id
        ]
        expanded_nodes = [
            node_payload(
                node_by_id[node_id],
                scores.get(node_id, 0.0),
                ["graph_expansion"],
                hop=hops[node_id],
            )
            for node_id in sorted(selected_ids - set(seed_hits), key=lambda item: (hops[item], item))
            if node_id in node_by_id
        ]
        edge_payloads = [edge_payload(edge) for edge in graph_edges]
        chunk_payloads = [chunk_payload(hit) for hit in source_chunks]
        packed_context = context_pack(
            query=query,
            chunks=source_chunks,
            related_edges=edge_payloads,
            nodes=seed_nodes + expanded_nodes,
            communities=communities,
            community_edges=community_edges,
        )
        trace_id = self._trace_id(repo_id, query, seed_hits.keys(), [hit.chunk.id for hit in source_chunks])

        return RetrievalTrace(
            repo_id=repo_id,
            query=query,
            max_hops=max_hops,
            trace_id=trace_id,
            seed_nodes=seed_nodes,
            expanded_nodes=expanded_nodes,
            source_chunks=chunk_payloads,
            related_edges=edge_payloads,
            community_summaries=communities,
            community_edges=community_edges,
            context_pack=packed_context,
        )

    def build_source_chunks(
        self,
        *,
        repo_id: str,
        repo_path: str,
        nodes: list[CodeGraphNode],
    ) -> list[CodeChunkRecord]:
        from backend.app.services.chunk_builder import build_source_chunks

        return build_source_chunks(repo_id=repo_id, repo_path=repo_path, nodes=nodes)

    def _trace_id(
        self,
        repo_id: str,
        query: str,
        seed_node_ids,
        chunk_ids: list[str],
    ) -> str:
        return stable_id(repo_id, "trace", query, *sorted(seed_node_ids), *chunk_ids)

    def _llm(self) -> LLMGateway:
        if self.llm is None:
            self.llm = LLMGateway(self.settings)
        return self.llm

    def _max_source_chunks(self) -> int:
        return max(1, self.settings.graphrag_max_source_chunks or DEFAULT_MAX_SOURCE_CHUNKS)

    def _context_token_budget(self) -> int:
        return max(1, self.settings.graphrag_context_token_budget or DEFAULT_CONTEXT_TOKENS)
