from typing import Any

from backend.app.services.graphrag import RetrievalTrace
from backend.app.services.wiki.diagrams.models import EDGE_LABEL_ORDER, _MermaidGroup
from backend.app.services.wiki.sources import _source_ref_href, _source_ref_label


def _graph_refs_from_trace(trace: RetrievalTrace) -> set[str]:
    refs: set[str] = set()
    for node in [*trace.seed_nodes, *trace.expanded_nodes]:
        node_id = node.get("id")
        if isinstance(node_id, str) and node_id:
            refs.add(node_id)
    for edge in trace.related_edges:
        for key in ("id", "source_id", "target_id", "source", "target"):
            value = edge.get(key)
            if isinstance(value, str) and value:
                refs.add(value)
    return refs


def _community_index(
    communities: list[dict[str, object]],
    *,
    preferred_level: int | None = None,
) -> dict[str, _MermaidGroup]:
    index: dict[str, _MermaidGroup] = {}
    visible = _communities_for_level(communities, preferred_level=preferred_level)
    for rank, community in enumerate(visible):
        community_id = str(community.get("id") or "")
        if not community_id:
            continue
        label = str(community.get("name") or community_id.rsplit(":", 1)[-1])
        group = _MermaidGroup(
            key=f"community:{community_id}",
            label=label,
            kind="community",
            rank=rank,
        )
        raw_node_ids = [
            *_string_list(community.get("matched_node_ids")),
            *_string_list(community.get("node_ids")),
        ]
        for node_id in raw_node_ids:
            if node_id:
                index.setdefault(node_id, group)
    return index


def _communities_for_level(
    communities: list[dict[str, object]],
    *,
    preferred_level: int | None,
) -> list[dict[str, object]]:
    if preferred_level is not None:
        return [
            community
            for community in communities
            if int(community.get("level") or 0) == preferred_level
        ]
    level = max((int(community.get("level") or 0) for community in communities), default=0)
    selected = [
        community
        for community in communities
        if int(community.get("level") or 0) == level
    ]
    return selected or communities


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _abstract_group_for_node(
    node: dict[str, object],
    *,
    community_index: dict[str, _MermaidGroup],
    group_mode: str,
) -> _MermaidGroup:
    node_id = str(node.get("id") or "")
    if group_mode == "community" and node_id in community_index:
        return community_index[node_id]

    metadata = node.get("metadata") if isinstance(node.get("metadata"), dict) else {}
    name = str(node.get("name") or node_id)
    if str(node.get("type") or "") == "module" and metadata.get("external"):
        return _MermaidGroup(
            key=f"external:{name}",
            label=f"External: {name}",
            kind="external",
            rank=90,
        )

    file_path = str(node.get("file_path") or "")
    if file_path:
        return _MermaidGroup(
            key=f"file:{file_path}",
            label=_component_label(file_path),
            kind="file",
            rank=20,
        )

    return _MermaidGroup(
        key=f"node:{node_id}",
        label=_mermaid_label(node),
        kind="node",
        rank=80,
    )


def _component_label(file_path: str) -> str:
    parts = [part for part in file_path.split("/") if part]
    if len(parts) >= 2:
        return f"{parts[-2]}/{parts[-1]}"
    return file_path


def _edge_endpoint(edge: dict[str, object], primary: str, fallback: str) -> str:
    value = edge.get(primary) or edge.get(fallback)
    return str(value or "")


def _edge_confidence(edge: dict[str, object]) -> float:
    confidence = edge.get("confidence")
    if isinstance(confidence, int | float):
        return float(confidence)
    return 1.0


def _edge_label(counts: dict[str, int]) -> str:
    labels = []
    for edge_type in EDGE_LABEL_ORDER:
        count = counts.get(edge_type, 0)
        if not count:
            continue
        label = edge_type.replace("_", " ")
        labels.append(f"{label} x{count}" if count > 1 else label)
    return _mermaid_edge_text(" / ".join(labels))


def _sequence_edge_label(counts: dict[str, int]) -> str:
    labels = []
    for edge_type in ("routes_to", "calls", "imports"):
        count = counts.get(edge_type, 0)
        if not count:
            continue
        label = edge_type.replace("_", " ")
        labels.append(f"{label} x{count}" if count > 1 else label)
    return _mermaid_edge_text(" / ".join(labels))


def _sequence_edge_is_runtime(counts: dict[str, int]) -> bool:
    return bool(counts.get("routes_to") or counts.get("calls"))


def _section_sources_line(source_refs: list[dict[str, Any]]) -> str:
    refs = [
        f"[{_source_ref_label(ref)}]({_source_ref_href(ref)})"
        for ref in source_refs[:6]
    ]
    return f"Sources: {' '.join(refs)}" if refs else ""


def _mermaid_label(node: dict[str, object]) -> str:
    name = str(node.get("name") or node.get("id") or "")
    node_type = str(node.get("type") or "")
    return _mermaid_text(f"{name} ({node_type})")


def _mermaid_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', "'").replace("\n", " ")[:80]


def _mermaid_edge_text(value: str) -> str:
    return _mermaid_text(value).replace("|", "/")


def _mermaid_sequence_text(value: str) -> str:
    return _mermaid_edge_text(value).replace(":", " -")


def _mermaid_class_text(value: str) -> str:
    return (
        _mermaid_edge_text(value)
        .replace("{", "(")
        .replace("}", ")")
        .replace(":", " -")
    )
