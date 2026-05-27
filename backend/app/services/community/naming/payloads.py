from typing import Any

from backend.app.database import GraphCommunityRecord
from backend.app.services.community.naming.constants import (
    MAX_COMMUNITY_EDGES,
    MAX_COMMUNITY_FILES,
    MAX_COMMUNITY_SYMBOLS,
)
from backend.app.services.graph import CodeGraphEdge, CodeGraphNode


def naming_payload(
    repo_id: str,
    repo_name: str,
    repo_path: str,
    communities: list[GraphCommunityRecord],
    node_by_id: dict[str, CodeGraphNode],
    edges: list[CodeGraphEdge],
    *,
    all_communities: list[GraphCommunityRecord] | None = None,
) -> dict[str, Any]:
    community_by_id = {
        community.id: community
        for community in (all_communities or communities)
    }
    return {
        "repo": {
            "id": repo_id,
            "name": repo_name,
            "path": repo_path,
        },
        "task": (
            "Name and summarize graph communities using only the provided files, symbols, "
            "deterministic summaries, and graph relationships. Keep node membership unchanged."
        ),
        "communities": [
            community_payload(community, node_by_id, edges, community_by_id=community_by_id)
            for community in communities
        ],
        "naming_rules": [
            "Use concise developer-facing subsystem names, 2-6 words.",
            "Prefer capability/workflow names over generic layer names.",
            "Avoid names like Backend Subsystem, Frontend Subsystem, Community 1, Cluster 23, Misc, Core.",
            "Do not invent modules, products, files, or dependencies.",
            "Return one object per input community id.",
        ],
        "summary_rules": [
            "Write a fresh source-grounded summary, not a copy of the deterministic summary.",
            "Describe responsibility, important files or symbols, and boundary dependencies.",
            "Keep each summary to one or two concise sentences.",
            "Call out unclear boundaries only when the graph evidence supports that uncertainty.",
        ],
        "required_json_shape": {
            "communities": [
                {
                    "id": "community-id",
                    "name": "GraphRAG Retrieval",
                    "summary": "One source-grounded sentence describing responsibility and boundaries.",
                }
            ]
        },
    }


def community_payload(
    community: GraphCommunityRecord,
    node_by_id: dict[str, CodeGraphNode],
    edges: list[CodeGraphEdge],
    *,
    community_by_id: dict[str, GraphCommunityRecord] | None = None,
) -> dict[str, Any]:
    node_ids = set(community.node_ids)
    files = sorted(
        {
            node.file_path
            for node_id in community.node_ids
            if (node := node_by_id.get(node_id)) is not None and node.file_path
        }
    )
    symbols = [
        {
            "name": node.name,
            "type": node.type,
            "file_path": node.file_path,
        }
        for node_id in community.node_ids
        if (node := node_by_id.get(node_id)) is not None and node.type != "file"
    ]
    internal_edges = [
        edge_payload(edge, node_by_id)
        for edge in edges
        if edge.source_id in node_ids and edge.target_id in node_ids
    ][:MAX_COMMUNITY_EDGES]
    boundary_edges = [
        edge_payload(edge, node_by_id)
        for edge in edges
        if (edge.source_id in node_ids) ^ (edge.target_id in node_ids)
    ][:MAX_COMMUNITY_EDGES]
    parent = (
        community_by_id.get(community.parent_id)
        if community_by_id is not None and isinstance(community.parent_id, str)
        else None
    )
    payload = {
        "id": community.id,
        "current_name": community.name,
        "level": community.level,
        "parent_id": community.parent_id,
        "parent_name": parent.name if parent is not None else None,
        "ancestor_names": _ancestor_names(community, community_by_id or {}),
        "rank": community.rank,
        "node_count": len(community.node_ids),
        "files": files[:MAX_COMMUNITY_FILES],
        "symbols": symbols[:MAX_COMMUNITY_SYMBOLS],
        "deterministic_summary": community.summary,
        "internal_edges": internal_edges,
        "boundary_edges": boundary_edges,
    }
    return {key: value for key, value in payload.items() if value not in (None, [])}


def edge_payload(
    edge: CodeGraphEdge,
    node_by_id: dict[str, CodeGraphNode],
) -> dict[str, Any]:
    source = node_by_id.get(edge.source_id)
    target = node_by_id.get(edge.target_id)
    return {
        "type": edge.type,
        "source": source.name if source else edge.source_id,
        "source_type": source.type if source else "",
        "target": target.name if target else edge.target_id,
        "target_type": target.type if target else "",
        "confidence": edge.confidence,
    }


def _ancestor_names(
    community: GraphCommunityRecord,
    community_by_id: dict[str, GraphCommunityRecord],
) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    parent_id = community.parent_id
    while isinstance(parent_id, str) and parent_id and parent_id not in seen:
        seen.add(parent_id)
        parent = community_by_id.get(parent_id)
        if parent is None:
            break
        names.append(parent.name)
        parent_id = parent.parent_id
    return list(reversed(names))
