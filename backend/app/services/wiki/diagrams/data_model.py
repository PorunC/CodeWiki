import re

from backend.app.services.graphrag import RetrievalTrace
from backend.app.services.wiki.diagrams.models import (
    MAX_MERMAID_CLASS_FIELDS,
    MAX_MERMAID_CLASS_NODES,
    MAX_MERMAID_SURFACES,
    SURFACE_NODE_TYPES,
    _MermaidGroup,
)
from backend.app.services.wiki.diagrams.rendering import (
    _abstract_group_for_node,
    _community_index,
    _edge_endpoint,
    _float_value,
    _int_value,
    _mermaid_class_text,
    _mermaid_label,
    _mermaid_text,
    _metadata_dict,
)


def _data_model_diagram(
    trace: RetrievalTrace,
    nodes: dict[str, dict[str, object]],
) -> list[str]:
    selected = _select_data_nodes([*trace.seed_nodes, *trace.expanded_nodes])
    if not selected:
        return []

    aliases = _class_aliases(selected)
    lines = ["classDiagram"]
    for node in selected:
        node_id = str(node.get("id") or "")
        alias = aliases.get(node_id)
        if not alias:
            continue
        lines.append(f"  class {alias}")
        label = _class_display_label(node)
        if label != alias:
            lines.append(f"  {alias} : {_mermaid_class_text(label)}")
        for field in _data_node_fields(node)[:MAX_MERMAID_CLASS_FIELDS]:
            lines.append(f"  {alias} : +{_mermaid_class_text(field)}")

    selected_ids = {str(node.get("id") or "") for node in selected}
    for edge in trace.related_edges:
        if edge.get("type") != "inherits":
            continue
        source_id = _edge_endpoint(edge, "source_id", "source")
        target_id = _edge_endpoint(edge, "target_id", "target")
        if source_id in selected_ids and target_id in selected_ids:
            source_alias = aliases.get(source_id)
            target_alias = aliases.get(target_id)
            if source_alias and target_alias:
                lines.append(f"  {target_alias} <|-- {source_alias}")
    return lines if len(lines) > 1 else []


def _key_surface_diagram(
    trace: RetrievalTrace,
    nodes: dict[str, dict[str, object]],
) -> list[str]:
    community_index = _community_index(trace.community_summaries)
    surfaces = _select_surface_nodes([*trace.seed_nodes, *trace.expanded_nodes])
    if not surfaces:
        return []

    groups: dict[str, _MermaidGroup] = {}
    surface_aliases: dict[str, str] = {}
    lines = ["flowchart TD"]
    for surface in surfaces:
        node_id = str(surface.get("id") or "")
        if not node_id or node_id not in nodes:
            continue
        group = _abstract_group_for_node(
            surface,
            community_index=community_index,
            group_mode="community",
        )
        if group.kind != "community":
            group = _abstract_group_for_node(
                surface,
                community_index=community_index,
                group_mode="file",
            )
        groups[group.key] = group
        surface_aliases[node_id] = f"S{len(surface_aliases)}"

    group_aliases = {
        key: f"G{index}"
        for index, key in enumerate(
            sorted(groups, key=lambda key: (groups[key].rank, groups[key].label, key))
        )
    }
    for key in group_aliases:
        lines.append(f'  {group_aliases[key]}["{_mermaid_text(groups[key].label)}"]')
    for surface in surfaces:
        node_id = str(surface.get("id") or "")
        surface_alias = surface_aliases.get(node_id)
        if surface_alias is None:
            continue
        group = _abstract_group_for_node(
            surface,
            community_index=community_index,
            group_mode="community",
        )
        if group.kind != "community":
            group = _abstract_group_for_node(
                surface,
                community_index=community_index,
                group_mode="file",
            )
        group_alias = group_aliases.get(group.key)
        if group_alias is None:
            continue
        lines.append(f'  {surface_alias}["{_surface_label(surface)}"]')
        lines.append(f"  {group_alias} --> {surface_alias}")

    return lines if len(lines) > 1 else []


def _select_surface_nodes(nodes: list[dict[str, object]]) -> list[dict[str, object]]:
    candidates = [
        node
        for node in nodes
        if str(node.get("type") or "") in SURFACE_NODE_TYPES
    ]
    return sorted(
        candidates,
        key=lambda node: (
            _surface_rank(str(node.get("type") or "")),
            _int_value(node.get("hop")),
            -_float_value(node.get("score")),
            str(node.get("file_path") or ""),
            str(node.get("name") or ""),
        ),
    )[:MAX_MERMAID_SURFACES]


def _select_data_nodes(nodes: list[dict[str, object]]) -> list[dict[str, object]]:
    candidates = [
        node
        for node in nodes
        if str(node.get("type") or "") in {"class", "schema", "interface"}
    ]
    return sorted(
        candidates,
        key=lambda node: (
            _surface_rank(str(node.get("type") or "")),
            _int_value(node.get("hop")),
            -_float_value(node.get("score")),
            str(node.get("file_path") or ""),
            str(node.get("name") or ""),
        ),
    )[:MAX_MERMAID_CLASS_NODES]


def _surface_rank(node_type: str) -> int:
    return {
        "endpoint": 0,
        "schema": 1,
        "class": 2,
        "interface": 3,
    }.get(node_type, 9)


def _surface_label(node: dict[str, object]) -> str:
    node_type = str(node.get("type") or "")
    metadata = _metadata_dict(node)
    if node_type == "endpoint":
        method = str(metadata.get("route_method") or "").upper()
        route_path = str(metadata.get("route_path") or "")
        if method or route_path:
            return _mermaid_text(" ".join(part for part in [method, route_path] if part))
    return _mermaid_label(node)


def _class_aliases(nodes: list[dict[str, object]]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    used: set[str] = set()
    for index, node in enumerate(nodes):
        node_id = str(node.get("id") or "")
        if not node_id:
            continue
        base = _class_identifier(str(node.get("name") or f"Data{index}"))
        alias = base
        suffix = 2
        while alias in used:
            alias = f"{base}{suffix}"
            suffix += 1
        used.add(alias)
        aliases[node_id] = alias
    return aliases


def _class_identifier(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_]", "_", value).strip("_")
    if not cleaned:
        return "DataModel"
    if cleaned[0].isdigit():
        cleaned = f"Data{cleaned}"
    return cleaned[:48]


def _class_display_label(node: dict[str, object]) -> str:
    name = str(node.get("name") or "")
    node_type = str(node.get("type") or "")
    return f"{name} ({node_type})" if node_type and node_type != "class" else name


def _data_node_fields(node: dict[str, object]) -> list[str]:
    metadata = _metadata_dict(node)
    fields = metadata.get("fields")
    if isinstance(fields, list):
        return [str(field) for field in fields if field is not None and str(field).strip()]
    signature = metadata.get("signature")
    if isinstance(signature, str) and signature:
        return [signature]
    bases = metadata.get("bases")
    if isinstance(bases, list):
        return [f"extends {base}" for base in bases if base]
    return []
