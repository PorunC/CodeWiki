import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.app.config import Settings, get_settings
from backend.app.database import (
    CodeChunkEmbeddingRecord,
    CodeChunkRecord,
    CodeChunkSearchHit,
    SQLiteStore,
    get_store,
)
from backend.app.services.graph_builder import CodeGraphEdge, CodeGraphNode
from backend.app.services.llm_gateway import LLMGateway

SOURCE_NODE_TYPES = {"file", "class", "function", "method", "schema", "endpoint"}
SEED_NODE_TYPES = SOURCE_NODE_TYPES | {"module"}
EDGE_WEIGHTS = {
    "calls": 1.0,
    "routes_to": 1.0,
    "inherits": 0.9,
    "imports": 0.82,
    "exports": 0.78,
    "defines": 0.72,
    "contains": 0.58,
}
MAX_SEED_NODES = 12
MAX_EXPANDED_NODES = 60
MAX_RELATED_EDGES = 140
DEFAULT_MAX_SOURCE_CHUNKS = 20
DEFAULT_CONTEXT_TOKENS = 8000
TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|[0-9]+")


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
class _NodeHit:
    node_id: str
    score: float
    reasons: set[str] = field(default_factory=set)


@dataclass
class _ChunkHit:
    chunk: CodeChunkRecord
    score: float
    reasons: set[str] = field(default_factory=set)


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
        repo = self.store.get_repo(repo_id)
        if repo is None:
            raise ValueError(f"Repository not found: {repo_id}")

        nodes, _edges = self.store.get_graph(repo_id)
        if not nodes:
            return GraphRAGBuildResult(repo_id=repo_id, status="empty_graph", chunk_count=0)

        chunks = self._build_source_chunks(repo_id=repo_id, repo_path=repo.path, nodes=nodes)
        self.store.replace_code_chunks(repo_id, chunks)

        embedding_count = 0
        embedding_model: str | None = None
        if include_embeddings and chunks:
            embedding_count, embedding_model = await self._embed_chunks(repo_id, chunks)

        return GraphRAGBuildResult(
            repo_id=repo_id,
            status="built",
            chunk_count=len(chunks),
            embedding_count=embedding_count,
            embedding_model=embedding_model,
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
        seed_hits = self._seed_from_symbols(query, nodes)
        fts_hits = self._search_fts(repo_id, query)
        vector_hits = await self._search_vectors(repo_id, query, chunks) if include_embeddings else []
        self._merge_chunk_hits_into_seeds(seed_hits, fts_hits + vector_hits, node_by_id)

        if not seed_hits:
            self._add_overview_fallback_seeds(seed_hits, nodes)

        seed_hits = dict(
            sorted(seed_hits.items(), key=lambda item: item[1].score, reverse=True)[:MAX_SEED_NODES]
        )
        selected_ids, hops, scores = self._expand(seed_hits, edges, max_hops=max_hops)
        related_edges = self._related_edges(edges, selected_ids)
        source_chunks = self._select_source_chunks(
            repo_id=repo_id,
            selected_ids=selected_ids,
            seed_ids=set(seed_hits),
            node_scores=scores,
            fts_hits=fts_hits,
            vector_hits=vector_hits,
        )
        communities = self._community_summaries(repo_id, selected_ids)

        seed_nodes = [
            self._node_payload(node_by_id[node_id], hit.score, sorted(hit.reasons), hop=0)
            for node_id, hit in seed_hits.items()
            if node_id in node_by_id
        ]
        expanded_nodes = [
            self._node_payload(
                node_by_id[node_id],
                scores.get(node_id, 0.0),
                ["graph_expansion"],
                hop=hops[node_id],
            )
            for node_id in sorted(selected_ids - set(seed_hits), key=lambda item: (hops[item], item))
            if node_id in node_by_id
        ]
        edge_payloads = [self._edge_payload(edge) for edge in related_edges]
        chunk_payloads = [self._chunk_payload(hit) for hit in source_chunks]
        context_pack = self._context_pack(
            query=query,
            chunks=source_chunks,
            related_edges=edge_payloads,
            nodes=seed_nodes + expanded_nodes,
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
            context_pack=context_pack,
        )

    def build_source_chunks(
        self,
        *,
        repo_id: str,
        repo_path: str,
        nodes: list[CodeGraphNode],
    ) -> list[CodeChunkRecord]:
        return self._build_source_chunks(repo_id=repo_id, repo_path=repo_path, nodes=nodes)

    def _build_source_chunks(
        self,
        *,
        repo_id: str,
        repo_path: str,
        nodes: list[CodeGraphNode],
    ) -> list[CodeChunkRecord]:
        root = Path(repo_path).resolve()
        line_cache: dict[str, list[str]] = {}
        chunks: list[CodeChunkRecord] = []
        seen: set[tuple[str, int, int, str]] = set()

        for node in sorted(nodes, key=lambda item: item.type == "file"):
            if node.type not in SOURCE_NODE_TYPES or not node.file_path:
                continue
            lines = line_cache.get(node.file_path)
            if lines is None:
                file_path = (root / node.file_path).resolve()
                if not file_path.is_file() or not file_path.is_relative_to(root):
                    line_cache[node.file_path] = []
                    continue
                lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
                line_cache[node.file_path] = lines
            if not lines:
                continue

            start_line = node.start_line or 1
            end_line = node.end_line or (len(lines) if node.type == "file" else start_line)
            start_line = max(1, min(start_line, len(lines)))
            end_line = max(start_line, min(end_line, len(lines)))
            content = "\n".join(lines[start_line - 1 : end_line])
            if not content.strip():
                continue
            content = f"{content}\n"
            content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
            dedupe_key = (node.file_path, start_line, end_line, content_hash)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            chunk_id = self._chunk_id(repo_id, node.id, node.file_path, start_line, end_line, content_hash)
            chunks.append(
                CodeChunkRecord(
                    id=chunk_id,
                    repo_id=repo_id,
                    node_id=node.id,
                    file_path=node.file_path,
                    start_line=start_line,
                    end_line=end_line,
                    content=content,
                    content_hash=content_hash,
                    token_count=_estimate_tokens(content),
                )
            )
        return sorted(chunks, key=lambda chunk: (chunk.file_path, chunk.start_line, chunk.end_line))

    async def _embed_chunks(
        self,
        repo_id: str,
        chunks: list[CodeChunkRecord],
    ) -> tuple[int, str]:
        llm = self._llm()
        model = llm.router.profile_for("embedding").model
        records: list[CodeChunkEmbeddingRecord] = []
        for batch in _batched(chunks, 32):
            texts = [_embedding_text(chunk) for chunk in batch]
            vectors = await llm.embed(texts, task_type="embedding")
            for chunk, vector in zip(batch, vectors, strict=True):
                records.append(
                    CodeChunkEmbeddingRecord(
                        id=_stable_id(repo_id, "embedding", model, chunk.id, chunk.content_hash),
                        repo_id=repo_id,
                        chunk_id=chunk.id,
                        model=model,
                        dimensions=len(vector),
                        embedding=vector,
                        content_hash=chunk.content_hash,
                        created_at=None,
                    )
                )
        self.store.replace_code_chunk_embeddings(repo_id, model=model, embeddings=records)
        return len(records), model

    def _seed_from_symbols(
        self,
        query: str,
        nodes: list[CodeGraphNode],
    ) -> dict[str, _NodeHit]:
        query_lower = query.lower()
        query_terms = set(_terms(query))
        hits: dict[str, _NodeHit] = {}
        if not query_terms and not query_lower:
            return hits

        for node in nodes:
            if node.type not in SEED_NODE_TYPES:
                continue
            haystack = _node_haystack(node)
            name_lower = node.name.lower()
            name_terms = set(_terms(node.name))
            score = 0.0
            if name_lower == query_lower:
                score = 1.15
            elif name_lower in query_terms:
                score = 1.05
            elif query_lower and query_lower in haystack:
                score = 0.88
            elif name_lower and name_lower in query_lower:
                score = 0.82
            shared_terms = len(query_terms & name_terms)
            if shared_terms:
                score = max(score, 0.55 + shared_terms * 0.12)
            if not score and any(term in haystack for term in query_terms):
                score = 0.42
            if score:
                score += _node_type_boost(node.type)
                hits[node.id] = _NodeHit(node_id=node.id, score=min(score, 1.25), reasons={"symbol"})
        return hits

    def _search_fts(self, repo_id: str, query: str) -> list[CodeChunkSearchHit]:
        fts_query = _fts_query(query)
        if not fts_query:
            return []
        return self.store.search_code_chunks_fts(
            repo_id,
            fts_query,
            limit=self._max_source_chunks(),
        )

    async def _search_vectors(
        self,
        repo_id: str,
        query: str,
        chunks: list[CodeChunkRecord],
    ) -> list[CodeChunkSearchHit]:
        llm = self._llm()
        model = llm.router.profile_for("embedding").model
        if not self.store.list_code_chunk_embeddings(repo_id, model=model) and chunks:
            await self._embed_chunks(repo_id, chunks)
        vectors = await llm.embed([query], task_type="embedding")
        if not vectors:
            return []
        return self.store.search_code_chunk_embeddings(
            repo_id,
            model=model,
            query_embedding=vectors[0],
                limit=self._max_source_chunks(),
        )

    def _merge_chunk_hits_into_seeds(
        self,
        seed_hits: dict[str, _NodeHit],
        chunk_hits: list[CodeChunkSearchHit],
        node_by_id: dict[str, CodeGraphNode],
    ) -> None:
        file_nodes_by_path = {
            node.file_path: node.id
            for node in node_by_id.values()
            if node.type == "file" and node.file_path
        }
        for index, chunk_hit in enumerate(chunk_hits):
            node_id = chunk_hit.chunk.node_id or file_nodes_by_path.get(chunk_hit.chunk.file_path)
            if node_id not in node_by_id:
                continue
            score = max(0.25, chunk_hit.score - index * 0.01)
            existing = seed_hits.get(node_id)
            if existing:
                existing.score = max(existing.score, score)
                existing.reasons.add(chunk_hit.match_type)
            else:
                seed_hits[node_id] = _NodeHit(node_id=node_id, score=score, reasons={chunk_hit.match_type})

    def _add_overview_fallback_seeds(
        self,
        seed_hits: dict[str, _NodeHit],
        nodes: list[CodeGraphNode],
    ) -> None:
        for node in nodes:
            if node.type == "repository":
                seed_hits[node.id] = _NodeHit(node_id=node.id, score=0.4, reasons={"overview"})
                break
        for node in sorted(nodes, key=lambda item: item.file_path):
            if node.type == "file":
                seed_hits[node.id] = _NodeHit(node_id=node.id, score=0.35, reasons={"overview"})
                if len(seed_hits) >= 6:
                    break

    def _expand(
        self,
        seed_hits: dict[str, _NodeHit],
        edges: list[CodeGraphEdge],
        *,
        max_hops: int,
    ) -> tuple[set[str], dict[str, int], dict[str, float]]:
        adjacency: dict[str, list[CodeGraphEdge]] = {}
        for edge in edges:
            adjacency.setdefault(edge.source_id, []).append(edge)
            adjacency.setdefault(edge.target_id, []).append(edge)

        selected = set(seed_hits)
        hops = {node_id: 0 for node_id in seed_hits}
        scores = {node_id: hit.score for node_id, hit in seed_hits.items()}
        frontier = set(seed_hits)

        for hop in range(1, max_hops + 1):
            candidates: dict[str, tuple[float, CodeGraphEdge]] = {}
            for node_id in frontier:
                for edge in adjacency.get(node_id, []):
                    neighbor_id = edge.target_id if edge.source_id == node_id else edge.source_id
                    if neighbor_id in selected:
                        continue
                    edge_weight = EDGE_WEIGHTS.get(edge.type, 0.35) * edge.confidence
                    score = scores.get(node_id, 0.1) * edge_weight * (0.78 ** hop)
                    current = candidates.get(neighbor_id)
                    if current is None or score > current[0]:
                        candidates[neighbor_id] = (score, edge)

            if not candidates:
                break

            next_frontier: set[str] = set()
            for node_id, (score, _edge) in sorted(
                candidates.items(),
                key=lambda item: item[1][0],
                reverse=True,
            ):
                if len(selected) >= MAX_EXPANDED_NODES:
                    break
                selected.add(node_id)
                hops[node_id] = hop
                scores[node_id] = score
                next_frontier.add(node_id)
            frontier = next_frontier
            if len(selected) >= MAX_EXPANDED_NODES:
                break
        return selected, hops, scores

    def _related_edges(
        self,
        edges: list[CodeGraphEdge],
        selected_ids: set[str],
    ) -> list[CodeGraphEdge]:
        related = [
            edge
            for edge in edges
            if edge.source_id in selected_ids and edge.target_id in selected_ids
        ]
        return sorted(
            related,
            key=lambda edge: (
                -EDGE_WEIGHTS.get(edge.type, 0.35),
                edge.is_inferred,
                edge.type,
                edge.source_id,
                edge.target_id,
            ),
        )[:MAX_RELATED_EDGES]

    def _select_source_chunks(
        self,
        *,
        repo_id: str,
        selected_ids: set[str],
        seed_ids: set[str],
        node_scores: dict[str, float],
        fts_hits: list[CodeChunkSearchHit],
        vector_hits: list[CodeChunkSearchHit],
    ) -> list[_ChunkHit]:
        chunk_hits: dict[str, _ChunkHit] = {}

        def add_chunk(chunk: CodeChunkRecord, score: float, reason: str) -> None:
            existing = chunk_hits.get(chunk.id)
            if existing:
                existing.score = max(existing.score, score)
                existing.reasons.add(reason)
            else:
                chunk_hits[chunk.id] = _ChunkHit(chunk=chunk, score=score, reasons={reason})

        for hit in fts_hits:
            add_chunk(hit.chunk, hit.score, hit.match_type)
        for hit in vector_hits:
            add_chunk(hit.chunk, hit.score, hit.match_type)

        for chunk in self.store.get_code_chunks_by_node_ids(repo_id, list(selected_ids)):
            node_id = chunk.node_id or ""
            graph_score = node_scores.get(node_id, 0.2)
            reason = "seed_node" if node_id in seed_ids else "expanded_node"
            add_chunk(chunk, graph_score * (0.78 if node_id in seed_ids else 0.52), reason)

        selected_chunks = sorted(
            chunk_hits.values(),
            key=lambda item: (-item.score, item.chunk.file_path, item.chunk.start_line),
        )
        packed: list[_ChunkHit] = []
        token_total = 0
        for hit in selected_chunks:
            if len(packed) >= self._max_source_chunks():
                break
            if packed and token_total + hit.chunk.token_count > self._context_token_budget():
                continue
            packed.append(hit)
            token_total += hit.chunk.token_count
        return packed

    def _community_summaries(self, repo_id: str, selected_ids: set[str]) -> list[dict[str, object]]:
        communities = []
        for community in self.store.list_graph_communities(repo_id):
            overlap = sorted(set(community.node_ids) & selected_ids)
            if not overlap:
                continue
            communities.append(
                {
                    "id": community.id,
                    "name": community.name,
                    "level": community.level,
                    "summary": community.summary,
                    "matched_node_ids": overlap,
                }
            )
        return communities

    def _context_pack(
        self,
        *,
        query: str,
        chunks: list[_ChunkHit],
        related_edges: list[dict[str, object]],
        nodes: list[dict[str, object]],
    ) -> dict[str, object]:
        parts = [f"Query: {query}", "", "Source Chunks:"]
        for hit in chunks:
            chunk = hit.chunk
            parts.append(f"[{chunk.id}] {chunk.file_path}:{chunk.start_line}-{chunk.end_line}")
            parts.append(chunk.content.rstrip())
            parts.append("")
        parts.append("Graph Facts:")
        for edge in related_edges[:40]:
            parts.append(
                f"- {edge['source']} -[{edge['type']}]-> {edge['target']}"
                f" (confidence={edge['confidence']})"
            )
        text = "\n".join(parts).strip()
        return {
            "text": text,
            "token_count": _estimate_tokens(text),
            "node_count": len(nodes),
            "edge_count": len(related_edges),
            "chunk_count": len(chunks),
            "source_chunk_ids": [hit.chunk.id for hit in chunks],
            "node_ids": [str(node["id"]) for node in nodes],
            "edge_ids": [str(edge["id"]) for edge in related_edges],
        }

    def _node_payload(
        self,
        node: CodeGraphNode,
        score: float,
        reasons: list[str],
        *,
        hop: int,
    ) -> dict[str, object]:
        return {
            "id": node.id,
            "type": node.type,
            "name": node.name,
            "file_path": node.file_path,
            "start_line": node.start_line,
            "end_line": node.end_line,
            "language": node.language,
            "symbol_id": node.symbol_id,
            "score": round(score, 4),
            "reasons": reasons,
            "hop": hop,
            "metadata": node.metadata,
        }

    def _edge_payload(self, edge: CodeGraphEdge) -> dict[str, object]:
        return {
            "id": edge.id,
            "source": edge.source_id,
            "target": edge.target_id,
            "source_id": edge.source_id,
            "target_id": edge.target_id,
            "type": edge.type,
            "confidence": edge.confidence,
            "weight": edge.weight,
            "is_inferred": edge.is_inferred,
            "metadata": edge.metadata,
        }

    def _chunk_payload(self, hit: _ChunkHit) -> dict[str, object]:
        chunk = hit.chunk
        return {
            "id": chunk.id,
            "node_id": chunk.node_id,
            "file_path": chunk.file_path,
            "start_line": chunk.start_line,
            "end_line": chunk.end_line,
            "content": chunk.content,
            "content_hash": chunk.content_hash,
            "token_count": chunk.token_count,
            "score": round(hit.score, 4),
            "reasons": sorted(hit.reasons),
        }

    def _trace_id(
        self,
        repo_id: str,
        query: str,
        seed_node_ids,
        chunk_ids: list[str],
    ) -> str:
        return _stable_id(repo_id, "trace", query, *sorted(seed_node_ids), *chunk_ids)

    def _chunk_id(
        self,
        repo_id: str,
        node_id: str,
        file_path: str,
        start_line: int,
        end_line: int,
        content_hash: str,
    ) -> str:
        return _stable_id(repo_id, "chunk", node_id, file_path, str(start_line), str(end_line), content_hash)

    def _llm(self) -> LLMGateway:
        if self.llm is None:
            self.llm = LLMGateway(self.settings)
        return self.llm

    def _max_source_chunks(self) -> int:
        return max(1, self.settings.graphrag_max_source_chunks or DEFAULT_MAX_SOURCE_CHUNKS)

    def _context_token_budget(self) -> int:
        return max(1, self.settings.graphrag_context_token_budget or DEFAULT_CONTEXT_TOKENS)


def _node_haystack(node: CodeGraphNode) -> str:
    values: list[str] = [
        node.name,
        node.type,
        node.file_path,
        node.symbol_id or "",
        node.language or "",
    ]
    for key in ("signature", "docstring", "route_method", "route_path", "handler"):
        value = node.metadata.get(key)
        if isinstance(value, str):
            values.append(value)
    for key in ("fields", "bases", "decorators", "exports", "calls"):
        value = node.metadata.get(key)
        if isinstance(value, list):
            values.extend(str(item) for item in value if item is not None)
    return " ".join(values).lower()


def _node_type_boost(node_type: str) -> float:
    return {
        "endpoint": 0.12,
        "function": 0.1,
        "method": 0.1,
        "class": 0.08,
        "schema": 0.08,
        "file": 0.04,
        "module": -0.1,
    }.get(node_type, 0.0)


def _terms(value: str) -> list[str]:
    return [match.group(0).lower() for match in TOKEN_RE.finditer(value)]


def _fts_query(query: str) -> str:
    terms = []
    seen = set()
    for term in _terms(query):
        if term in seen:
            continue
        seen.add(term)
        terms.append(term)
    return " OR ".join(f'"{term}"' for term in terms[:16])


def _estimate_tokens(content: str) -> int:
    return max(1, len(re.findall(r"\S+", content)))


def _embedding_text(chunk: CodeChunkRecord) -> str:
    return f"{chunk.file_path}:{chunk.start_line}-{chunk.end_line}\n{chunk.content}"


def _stable_id(repo_id: str, kind: str, *parts: str) -> str:
    digest = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:24]
    return f"{repo_id}:{kind}:{digest}"


def _batched(items: list[Any], size: int):
    for index in range(0, len(items), size):
        yield items[index : index + size]
