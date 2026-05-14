from datetime import UTC, datetime

from backend.app.database import CodeChunkRecord, CodeChunkSearchHit
from backend.app.services.graph import CodeGraphEdge, CodeGraphNode
from backend.app.services.graphrag.models import ChunkHit

HYBRID_RANKING_WEIGHTS = {
    "semantic": 0.35,
    "keyword": 0.25,
    "graph_proximity": 0.20,
    "node_importance": 0.10,
    "source_freshness": 0.10,
}


def rank_source_chunks(
    chunks: list[CodeChunkRecord],
    *,
    nodes: list[CodeGraphNode],
    edges: list[CodeGraphEdge],
    seed_ids: set[str],
    hops: dict[str, int],
    fts_hits: list[CodeChunkSearchHit],
    vector_hits: list[CodeChunkSearchHit],
) -> list[ChunkHit]:
    keyword_scores = _hit_scores(fts_hits)
    semantic_scores = _hit_scores(vector_hits)
    node_by_id = {node.id: node for node in nodes}
    file_node_by_path = {
        node.file_path: node
        for node in nodes
        if node.type == "file" and node.file_path
    }
    centrality = _degree_centrality(nodes, edges)
    freshness = _freshness_scores(chunks, node_by_id, file_node_by_path)

    ranked: list[ChunkHit] = []
    for chunk in chunks:
        node_id = _chunk_node_id(chunk, node_by_id, file_node_by_path)
        semantic_score = semantic_scores.get(chunk.id, 0.0)
        keyword_score = keyword_scores.get(chunk.id, 0.0)
        graph_score = _graph_proximity_score(node_id, hops)
        centrality_score = centrality.get(node_id or "", 0.0)
        freshness_score = freshness.get(chunk.id, 0.0)
        components = {
            "semantic_score": semantic_score,
            "keyword_score": keyword_score,
            "graph_proximity_score": graph_score,
            "node_importance_score": centrality_score,
            "source_freshness_score": freshness_score,
        }
        score = (
            HYBRID_RANKING_WEIGHTS["semantic"] * semantic_score
            + HYBRID_RANKING_WEIGHTS["keyword"] * keyword_score
            + HYBRID_RANKING_WEIGHTS["graph_proximity"] * graph_score
            + HYBRID_RANKING_WEIGHTS["node_importance"] * centrality_score
            + HYBRID_RANKING_WEIGHTS["source_freshness"] * freshness_score
        )
        ranked.append(
            ChunkHit(
                chunk=chunk,
                score=score,
                reasons=_ranking_reasons(
                    semantic_score=semantic_score,
                    keyword_score=keyword_score,
                    graph_score=graph_score,
                    node_id=node_id,
                    seed_ids=seed_ids,
                ),
                score_components=components,
            )
        )

    return sorted(ranked, key=lambda item: (-item.score, item.chunk.file_path, item.chunk.start_line))


def _hit_scores(hits: list[CodeChunkSearchHit]) -> dict[str, float]:
    scores: dict[str, float] = {}
    for hit in hits:
        scores[hit.chunk.id] = max(scores.get(hit.chunk.id, 0.0), min(max(hit.score, 0.0), 1.0))
    return scores


def _chunk_node_id(
    chunk: CodeChunkRecord,
    node_by_id: dict[str, CodeGraphNode],
    file_node_by_path: dict[str, CodeGraphNode],
) -> str | None:
    if chunk.node_id in node_by_id:
        return chunk.node_id
    file_node = file_node_by_path.get(chunk.file_path)
    return file_node.id if file_node is not None else None


def _graph_proximity_score(node_id: str | None, hops: dict[str, int]) -> float:
    if node_id is None or node_id not in hops:
        return 0.0
    return 1.0 / (hops[node_id] + 1)


def _degree_centrality(
    nodes: list[CodeGraphNode],
    edges: list[CodeGraphEdge],
) -> dict[str, float]:
    degrees = {node.id: 0 for node in nodes}
    for edge in edges:
        if edge.source_id in degrees:
            degrees[edge.source_id] += 1
        if edge.target_id in degrees:
            degrees[edge.target_id] += 1
    max_degree = max(degrees.values(), default=0)
    if max_degree <= 0:
        return {node_id: 0.0 for node_id in degrees}
    return {node_id: degree / max_degree for node_id, degree in degrees.items()}


def _freshness_scores(
    chunks: list[CodeChunkRecord],
    node_by_id: dict[str, CodeGraphNode],
    file_node_by_path: dict[str, CodeGraphNode],
) -> dict[str, float]:
    timestamps = {
        chunk.id: _chunk_timestamp(chunk, node_by_id, file_node_by_path)
        for chunk in chunks
    }
    present_timestamps = [timestamp for timestamp in timestamps.values() if timestamp is not None]
    if not present_timestamps:
        return {chunk.id: 0.0 for chunk in chunks}
    min_timestamp = min(present_timestamps)
    max_timestamp = max(present_timestamps)
    if min_timestamp == max_timestamp:
        return {
            chunk_id: 1.0 if timestamp is not None else 0.0
            for chunk_id, timestamp in timestamps.items()
        }
    span = max_timestamp - min_timestamp
    return {
        chunk_id: ((timestamp - min_timestamp) / span if timestamp is not None else 0.0)
        for chunk_id, timestamp in timestamps.items()
    }


def _chunk_timestamp(
    chunk: CodeChunkRecord,
    node_by_id: dict[str, CodeGraphNode],
    file_node_by_path: dict[str, CodeGraphNode],
) -> float | None:
    candidates: list[CodeGraphNode] = []
    if chunk.node_id and chunk.node_id in node_by_id:
        candidates.append(node_by_id[chunk.node_id])
    file_node = file_node_by_path.get(chunk.file_path)
    if file_node is not None:
        candidates.append(file_node)
    for node in candidates:
        timestamp = _metadata_timestamp(node.metadata)
        if timestamp is not None:
            return timestamp
    return None


def _metadata_timestamp(metadata: dict[str, object]) -> float | None:
    for key in ("last_commit_at", "commit_time", "committed_at", "modified_at"):
        timestamp = _parse_timestamp(metadata.get(key))
        if timestamp is not None:
            return timestamp
    return None


def _parse_timestamp(value: object) -> float | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.timestamp()


def _ranking_reasons(
    *,
    semantic_score: float,
    keyword_score: float,
    graph_score: float,
    node_id: str | None,
    seed_ids: set[str],
) -> set[str]:
    reasons: set[str] = set()
    if semantic_score > 0:
        reasons.add("vector")
    if keyword_score > 0:
        reasons.add("fts")
    if graph_score > 0:
        reasons.add("seed_node" if node_id in seed_ids else "expanded_node")
    return reasons or {"hybrid_rank"}
