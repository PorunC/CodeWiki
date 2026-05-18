from backend.app.database import CodeChunkRecord, CodeChunkSearchHit, SQLiteStore
from backend.app.services.embedding_index import EmbeddingIndex
from backend.app.services.graph import CodeGraphNode
from backend.app.services.graphrag.constants import SEED_NODE_TYPES
from backend.app.services.graphrag.models import NodeHit
from backend.app.services.graphrag.utils import fts_query, node_haystack, node_type_boost, terms
from backend.app.services.llm_gateway import LLMGateway


def seed_from_symbols(
    query: str,
    nodes: list[CodeGraphNode],
    *,
    store: SQLiteStore | None = None,
    repo_id: str | None = None,
) -> dict[str, NodeHit]:
    query_lower = query.lower()
    query_terms = set(terms(query))
    hits: dict[str, NodeHit] = {}
    if not query_terms and not query_lower:
        return hits

    if store is not None and repo_id is not None:
        for search_hit in store.search_code_nodes(
            repo_id,
            query,
            types=sorted(SEED_NODE_TYPES),
            limit=32,
        ):
            hits[search_hit.node.id] = NodeHit(
                node_id=search_hit.node.id,
                score=min(1.3, max(0.35, search_hit.score)),
                reasons={*search_hit.reasons, "symbol_fts"},
            )

    for node in nodes:
        if node.type not in SEED_NODE_TYPES:
            continue
        haystack = node_haystack(node)
        name_lower = node.name.lower()
        name_terms = set(terms(node.name))
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
            score += node_type_boost(node.type)
            existing = hits.get(node.id)
            if existing:
                existing.score = max(existing.score, min(score, 1.25))
                existing.reasons.add("symbol")
            else:
                hits[node.id] = NodeHit(node_id=node.id, score=min(score, 1.25), reasons={"symbol"})
    return hits


def search_fts(
    store: SQLiteStore,
    repo_id: str,
    query: str,
    *,
    limit: int,
) -> list[CodeChunkSearchHit]:
    query_text = fts_query(query)
    if not query_text:
        return []
    return store.search_code_chunks_fts(repo_id, query_text, limit=limit)


async def search_vectors(
    store: SQLiteStore,
    llm: LLMGateway,
    repo_id: str,
    query: str,
    chunks: list[CodeChunkRecord],
    *,
    limit: int,
) -> list[CodeChunkSearchHit]:
    return await EmbeddingIndex(store, llm).search(repo_id, query, chunks, limit=limit)


def merge_chunk_hits_into_seeds(
    seed_hits: dict[str, NodeHit],
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
            seed_hits[node_id] = NodeHit(node_id=node_id, score=score, reasons={chunk_hit.match_type})


def add_overview_fallback_seeds(
    seed_hits: dict[str, NodeHit],
    nodes: list[CodeGraphNode],
) -> None:
    for node in nodes:
        if node.type == "repository":
            seed_hits[node.id] = NodeHit(node_id=node.id, score=0.4, reasons={"overview"})
            break
    for node in sorted(nodes, key=lambda item: item.file_path):
        if node.type == "file":
            seed_hits[node.id] = NodeHit(node_id=node.id, score=0.35, reasons={"overview"})
            if len(seed_hits) >= 6:
                break
