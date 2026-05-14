from backend.app.database import CodeChunkSearchHit, SQLiteStore
from backend.app.services.graph import CodeGraphEdge, CodeGraphNode
from backend.app.services.graph_provenance import edge_provenance, node_confidence, node_provenance
from backend.app.services.graphrag.models import ChunkHit
from backend.app.services.graphrag.ranking import rank_source_chunks
from backend.app.services.graphrag.utils import estimate_tokens


def select_source_chunks(
    store: SQLiteStore,
    *,
    repo_id: str,
    selected_ids: set[str],
    seed_ids: set[str],
    nodes: list[CodeGraphNode],
    edges: list[CodeGraphEdge],
    hops: dict[str, int],
    fts_hits: list[CodeChunkSearchHit],
    vector_hits: list[CodeChunkSearchHit],
    max_source_chunks: int,
    context_token_budget: int,
) -> list[ChunkHit]:
    candidates = {hit.chunk.id: hit.chunk for hit in [*fts_hits, *vector_hits]}

    for chunk in store.get_code_chunks_by_node_ids(repo_id, list(selected_ids)):
        candidates.setdefault(chunk.id, chunk)

    selected_chunks = rank_source_chunks(
        list(candidates.values()),
        nodes=nodes,
        edges=edges,
        seed_ids=seed_ids,
        hops=hops,
        fts_hits=fts_hits,
        vector_hits=vector_hits,
    )
    packed: list[ChunkHit] = []
    token_total = 0
    for hit in selected_chunks:
        if len(packed) >= max_source_chunks:
            break
        if packed and token_total + hit.chunk.token_count > context_token_budget:
            continue
        packed.append(hit)
        token_total += hit.chunk.token_count
    return packed


def community_summaries(store: SQLiteStore, repo_id: str, selected_ids: set[str]) -> list[dict[str, object]]:
    communities = []
    for community in store.list_graph_communities(repo_id):
        overlap = sorted(set(community.node_ids) & selected_ids)
        if not overlap:
            continue
        communities.append(
            {
                "id": community.id,
                "name": community.name,
                "level": community.level,
                "summary": community.summary,
                "node_count": len(community.node_ids),
                "node_ids": community.node_ids[:24],
                "matched_node_ids": overlap,
            }
        )
    return sorted(
        communities,
        key=lambda item: (-len(item["matched_node_ids"]), item["level"], item["name"]),
    )[:12]


def context_pack(
    *,
    query: str,
    chunks: list[ChunkHit],
    related_edges: list[dict[str, object]],
    nodes: list[dict[str, object]],
    communities: list[dict[str, object]],
) -> dict[str, object]:
    parts = [f"Query: {query}", "", "Source Chunks:"]
    for hit in chunks:
        chunk = hit.chunk
        parts.append(f"[{chunk.id}] {chunk.file_path}:{chunk.start_line}-{chunk.end_line}")
        parts.append(chunk.content.rstrip())
        parts.append("")
    if communities:
        parts.append("Community Summaries:")
        for community in communities[:12]:
            parts.append(
                f"- {community['name']} ({community['id']}): {community.get('summary') or ''}"
            )
        parts.append("")
    parts.append("Graph Facts:")
    for edge in related_edges[:40]:
        parts.append(
            f"- {edge['source']} -[{edge['type']}]-> {edge['target']}"
            f" (confidence={edge['confidence']}, level={edge.get('confidence_level')})"
        )
    text = "\n".join(parts).strip()
    return {
        "text": text,
        "token_count": estimate_tokens(text),
        "node_count": len(nodes),
        "edge_count": len(related_edges),
        "chunk_count": len(chunks),
        "community_count": len(communities),
        "source_chunk_ids": [hit.chunk.id for hit in chunks],
        "node_ids": [str(node["id"]) for node in nodes],
        "edge_ids": [str(edge["id"]) for edge in related_edges],
        "community_ids": [str(community["id"]) for community in communities],
    }


def node_payload(
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
        "confidence": node_confidence(node.metadata),
        "provenance": node_provenance(node.metadata),
        "metadata": node.metadata,
    }


def edge_payload(edge: CodeGraphEdge) -> dict[str, object]:
    return {
        "id": edge.id,
        "source": edge.source_id,
        "target": edge.target_id,
        "source_id": edge.source_id,
        "target_id": edge.target_id,
        "type": edge.type,
        "confidence": edge.confidence,
        "confidence_level": edge.metadata.get("confidence_level"),
        "weight": edge.weight,
        "is_inferred": edge.is_inferred,
        "provenance": edge_provenance(edge.metadata),
        "metadata": edge.metadata,
    }


def chunk_payload(hit: ChunkHit) -> dict[str, object]:
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
        "score_components": {
            key: round(value, 4)
            for key, value in hit.score_components.items()
        },
        "reasons": sorted(hit.reasons),
    }
