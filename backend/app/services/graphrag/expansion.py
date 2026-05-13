from backend.app.services.graph import CodeGraphEdge
from backend.app.services.graphrag.constants import EDGE_WEIGHTS, MAX_EXPANDED_NODES, MAX_RELATED_EDGES
from backend.app.services.graphrag.models import NodeHit


def expand(
    seed_hits: dict[str, NodeHit],
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


def related_edges(
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
