from backend.app.database import CodeChunkSearchHit, CodeWikiStore, GraphCommunityRecord
from backend.app.services.file_roles import is_wiki_noise_file
from backend.app.services.graph import CodeGraphEdge, CodeGraphNode
from backend.app.services.graph_provenance import edge_provenance, node_confidence, node_provenance
from backend.app.services.graphrag.models import ChunkHit
from backend.app.services.graphrag.ranking import rank_source_chunks
from backend.app.services.graphrag.utils import estimate_tokens

IGNORED_SOURCE_FILES = {"uv.lock", "package-lock.json", "pnpm-lock.yaml", "yarn.lock"}
MAX_COMMUNITY_SUMMARIES = 12
MAX_PARENT_SUMMARIES = 3
MAX_CHILD_SUMMARIES = 8
MAX_CHILDREN_PER_PARENT_IN_PROMPT = 4
MAX_COMMUNITY_EDGES = 16


def _is_ignored_source_file(file_path: str) -> bool:
    normalized = file_path.replace("\\", "/")
    return normalized.rsplit("/", 1)[-1] in IGNORED_SOURCE_FILES or is_wiki_noise_file(file_path)


def select_source_chunks(
    store: CodeWikiStore,
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
        if _is_ignored_source_file(hit.chunk.file_path):
            continue
        if hit.chunk.token_count > context_token_budget:
            continue
        if token_total + hit.chunk.token_count > context_token_budget:
            continue
        packed.append(hit)
        token_total += hit.chunk.token_count
    return packed


def community_summaries(store: CodeWikiStore, repo_id: str, selected_ids: set[str]) -> list[dict[str, object]]:
    matched: list[dict[str, object]] = []
    all_communities = store.list_graph_communities(repo_id)
    by_id = {community.id: community for community in all_communities}
    parent_ids = {
        community.parent_id
        for community in all_communities
        if isinstance(community.parent_id, str) and community.parent_id
    }
    for community in store.list_graph_communities(repo_id):
        overlap = sorted(set(community.node_ids) & selected_ids)
        if not overlap:
            continue
        matched.append(
            {
                "id": community.id,
                "name": community.name,
                "level": community.level,
                "parent_id": community.parent_id,
                "summary": community.summary,
                "node_count": len(community.node_ids),
                "matched_node_ids": overlap,
            }
        )
    leaves = [
        community
        for community in matched
        if str(community.get("id") or "") not in parent_ids
    ]
    parents = [
        community
        for community in matched
        if str(community.get("id") or "") in parent_ids or not community.get("parent_id")
    ]
    if not leaves:
        return sorted(
            matched,
            key=lambda item: (-_matched_node_count(item), _int_value(item.get("level")), str(item.get("name") or "")),
        )[:MAX_COMMUNITY_SUMMARIES]

    selected_leaves: list[dict[str, object]] = []
    siblings_by_parent: dict[str, int] = {}
    for child in sorted(
        leaves,
        key=lambda item: (
            -_matched_node_count(item),
            -_int_value(item.get("level")),
            str(item.get("name") or ""),
        ),
    ):
        parent_id = str(child.get("parent_id") or "")
        if siblings_by_parent.get(parent_id, 0) >= MAX_CHILDREN_PER_PARENT_IN_PROMPT:
            continue
        selected_leaves.append(child)
        siblings_by_parent[parent_id] = siblings_by_parent.get(parent_id, 0) + 1
        if len(selected_leaves) >= MAX_CHILD_SUMMARIES:
            break

    selected_parent_ids = _ancestor_ids(selected_leaves, by_id)
    selected_parents = [
        _community_summary_payload(parent, selected_ids, include_matches=True)
        for parent_id in selected_parent_ids
        if (parent := by_id.get(parent_id)) is not None
    ]
    if len(selected_parents) < MAX_PARENT_SUMMARIES:
        for parent_summary in sorted(
            parents,
            key=lambda item: (-_matched_node_count(item), str(item.get("name") or "")),
        ):
            if any(parent_summary["id"] == selected["id"] for selected in selected_parents):
                continue
            selected_parents.append(parent_summary)
            if len(selected_parents) >= MAX_PARENT_SUMMARIES:
                break

    return [*selected_parents[:MAX_PARENT_SUMMARIES], *selected_leaves][
        :MAX_COMMUNITY_SUMMARIES
    ]


def _ancestor_ids(
    communities: list[dict[str, object]],
    by_id: dict[str, GraphCommunityRecord],
) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for community in communities:
        parent_id = community.get("parent_id")
        while isinstance(parent_id, str) and parent_id:
            if parent_id in seen:
                break
            seen.add(parent_id)
            ids.append(parent_id)
            parent = by_id.get(parent_id)
            parent_id = getattr(parent, "parent_id", None)
    return ids


def _community_summary_payload(
    community: GraphCommunityRecord,
    selected_ids: set[str],
    *,
    include_matches: bool,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": community.id,
        "name": community.name,
        "level": community.level,
        "parent_id": community.parent_id,
        "summary": community.summary,
        "node_count": len(community.node_ids),
    }
    if include_matches:
        payload["matched_node_ids"] = sorted(set(community.node_ids) & selected_ids)
    return payload


def _matched_node_count(item: dict[str, object]) -> int:
    matched_node_ids = item.get("matched_node_ids")
    return len(matched_node_ids) if isinstance(matched_node_ids, list) else 0


def _int_value(value: object, default: int = 0) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def context_pack(
    *,
    query: str,
    chunks: list[ChunkHit],
    related_edges: list[dict[str, object]],
    nodes: list[dict[str, object]],
    communities: list[dict[str, object]],
    community_edges: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    parts = [f"Query: {query}", "", "Source Chunks:"]
    for hit in chunks:
        chunk = hit.chunk
        parts.append(f"[{chunk.id}] {chunk.file_path}:{chunk.start_line}-{chunk.end_line}")
        parts.append(chunk.content.rstrip())
        parts.append("")
    if communities:
        parts.append("Community Summaries:")
        parent_ids = {
            str(community.get("id"))
            for community in communities
            if _int_value(community.get("level")) == 0
        }
        for community in communities[:MAX_COMMUNITY_SUMMARIES]:
            level = _int_value(community.get("level"))
            label = "Architecture" if level == 0 else "Implementation" if level == 1 else "Detail"
            indent = "  " if level > 0 and str(community.get("parent_id") or "") in parent_ids else ""
            parts.append(
                f"{indent}[{label}] {community['name']} ({community['id']}): {community.get('summary') or ''}"
            )
        parts.append("")
    if community_edges:
        parts.append("Community Relationships:")
        for edge in community_edges[:MAX_COMMUNITY_EDGES]:
            parts.append(
                f"- {edge['source']} -[{edge['type']}]-> {edge['target']}"
                f" (confidence={edge['confidence']}, reason={edge.get('reason')})"
            )
        parts.append("")
    parts.append("Graph Facts:")
    for edge in related_edges[:40]:
        parts.append(
            f"- {edge['source']} -[{edge['type']}]-> {edge['target']}"
            f" (confidence={edge['confidence']}, level={edge.get('confidence_level')},"
            f" reason={edge.get('reason')})"
        )
    text = "\n".join(parts).strip()
    return {
        "text": text,
        "token_count": estimate_tokens(text),
        "node_count": len(nodes),
        "edge_count": len(related_edges),
        "community_edge_count": len(community_edges or []),
        "chunk_count": len(chunks),
        "community_count": len(communities),
        "source_chunk_ids": [hit.chunk.id for hit in chunks],
        "node_ids": [str(node["id"]) for node in nodes],
        "edge_ids": [str(edge["id"]) for edge in related_edges],
        "community_ids": [str(community["id"]) for community in communities],
        "community_edge_ids": [str(edge["id"]) for edge in community_edges or []],
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
        "reason": edge.metadata.get("reason"),
        "weight": edge.weight,
        "is_inferred": edge.is_inferred,
        "provenance": edge_provenance(edge.metadata),
        "metadata": edge.metadata,
    }


def community_edge_payloads(
    store: CodeWikiStore,
    repo_id: str,
    community_ids: set[str],
) -> list[dict[str, object]]:
    if not community_ids:
        return []
    payloads: list[dict[str, object]] = []
    for edge in store.list_graph_community_edges(repo_id):
        if (
            edge.source_community_id not in community_ids
            or edge.target_community_id not in community_ids
        ):
            continue
        payloads.append(
            {
                "id": edge.id,
                "source": edge.source_community_id,
                "target": edge.target_community_id,
                "type": edge.type,
                "confidence": edge.confidence,
                "reason": edge.reason,
            }
        )
        if len(payloads) >= MAX_COMMUNITY_EDGES:
            break
    return payloads


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
