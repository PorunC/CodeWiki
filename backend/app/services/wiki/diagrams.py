import re
from dataclasses import dataclass
from typing import Any

from backend.app.services.graph_rag import RetrievalTrace
from backend.app.services.wiki.sources import _source_ref_href, _source_ref_label

ABSTRACT_DIAGRAM_EDGE_TYPES = {"routes_to", "calls", "imports", "inherits", "exports"}
SOURCE_EDGE_TYPES = ABSTRACT_DIAGRAM_EDGE_TYPES | {"contains", "defines"}
SURFACE_NODE_TYPES = {"endpoint", "class", "schema", "interface"}
EDGE_LABEL_ORDER = ("routes_to", "calls", "imports", "inherits", "exports")
MAX_MERMAID_EDGES = 28
MAX_MERMAID_COMPONENTS = 10
MAX_MERMAID_ABSTRACT_EDGES = 14
MAX_MERMAID_SURFACES = 10
MAX_MERMAID_DIAGRAMS = 4
MAX_MERMAID_SEQUENCE_MESSAGES = 8
MAX_MERMAID_CLASS_NODES = 8
MAX_MERMAID_CLASS_FIELDS = 6

@dataclass(frozen=True)
class _MermaidGroup:
    key: str
    label: str
    kind: str
    rank: int


@dataclass
class _MermaidEdgeAggregate:
    source_key: str
    target_key: str
    counts: dict[str, int]
    confidence_total: float = 0.0
    evidence_count: int = 0


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


def _mermaid_from_trace(
    trace: RetrievalTrace,
    *,
    title: str | None = None,
    source_refs: list[dict[str, Any]] | None = None,
) -> str:
    nodes = {
        str(node["id"]): node
        for node in [*trace.seed_nodes, *trace.expanded_nodes]
        if "id" in node
    }
    if not nodes:
        return ""

    diagrams: list[tuple[str, list[str]]] = []
    component_groups, component_edges = _component_groups_and_edges(trace, nodes)
    component_diagram = _abstract_component_diagram(component_groups, component_edges)
    if component_diagram:
        diagrams.append(("Component map", component_diagram))

    data_flow_diagram = _data_flow_diagram(component_groups, component_edges)
    if data_flow_diagram:
        diagrams.append(("Data flow", data_flow_diagram))

    sequence_diagram = _interaction_sequence_diagram(component_groups, component_edges)
    if sequence_diagram:
        diagrams.append(("Interaction flow", sequence_diagram))

    data_diagram = _data_model_diagram(trace, nodes)
    if data_diagram:
        diagrams.append(("Data model", data_diagram))

    surface_diagram = _key_surface_diagram(trace, nodes)
    if surface_diagram:
        diagrams.append(("Key surfaces", surface_diagram))

    if not diagrams:
        return ""

    graph_title = f"{title} graph overview" if title else "Graph overview"
    lines = ["## Graph", "", f"Title: {graph_title}"]
    for diagram_title, diagram_lines in diagrams[:MAX_MERMAID_DIAGRAMS]:
        lines.extend(["", f"### {diagram_title}", "", "```mermaid"])
        lines.extend(diagram_lines)
        lines.append("```")
    source_line = _section_sources_line(source_refs or [])
    if source_line:
        lines.extend(["", source_line])
    return "\n".join(lines)


def _component_groups_and_edges(
    trace: RetrievalTrace,
    nodes: dict[str, dict[str, object]],
) -> tuple[dict[str, _MermaidGroup], list[_MermaidEdgeAggregate]]:
    community_groups, community_edges = _aggregate_component_edges(
        trace,
        nodes,
        group_mode="community",
    )
    if community_edges and len(community_groups) > 1:
        return community_groups, community_edges

    file_groups, file_edges = _aggregate_component_edges(
        trace,
        nodes,
        group_mode="file",
    )
    if file_edges and len(file_groups) > 1:
        return file_groups, file_edges
    return {}, []


def _abstract_component_diagram(
    groups: dict[str, _MermaidGroup],
    edges: list[_MermaidEdgeAggregate],
) -> list[str]:
    if not edges or len(groups) <= 1:
        return []
    return _render_component_diagram(groups, edges)


def _aggregate_component_edges(
    trace: RetrievalTrace,
    nodes: dict[str, dict[str, object]],
    *,
    group_mode: str,
) -> tuple[dict[str, _MermaidGroup], list[_MermaidEdgeAggregate]]:
    community_index = _community_index(trace.community_summaries)
    groups: dict[str, _MermaidGroup] = {}
    aggregates: dict[tuple[str, str], _MermaidEdgeAggregate] = {}

    for edge in trace.related_edges:
        edge_type = str(edge.get("type") or "")
        if edge_type not in ABSTRACT_DIAGRAM_EDGE_TYPES:
            continue
        source_id = _edge_endpoint(edge, "source_id", "source")
        target_id = _edge_endpoint(edge, "target_id", "target")
        source_node = nodes.get(source_id)
        target_node = nodes.get(target_id)
        if source_node is None or target_node is None:
            continue

        source_group = _abstract_group_for_node(
            source_node,
            community_index=community_index,
            group_mode=group_mode,
        )
        target_group = _abstract_group_for_node(
            target_node,
            community_index=community_index,
            group_mode=group_mode,
        )
        if source_group.key == target_group.key:
            continue

        groups[source_group.key] = source_group
        groups[target_group.key] = target_group
        aggregate_key = (source_group.key, target_group.key)
        aggregate = aggregates.setdefault(
            aggregate_key,
            _MermaidEdgeAggregate(
                source_key=source_group.key,
                target_key=target_group.key,
                counts={},
            ),
        )
        aggregate.counts[edge_type] = aggregate.counts.get(edge_type, 0) + 1
        aggregate.confidence_total += _edge_confidence(edge)
        aggregate.evidence_count += 1

    selected = _select_component_edges(list(aggregates.values()))
    selected_group_keys = {edge.source_key for edge in selected} | {edge.target_key for edge in selected}
    return (
        {key: group for key, group in groups.items() if key in selected_group_keys},
        selected,
    )


def _select_component_edges(edges: list[_MermaidEdgeAggregate]) -> list[_MermaidEdgeAggregate]:
    selected: list[_MermaidEdgeAggregate] = []
    selected_groups: set[str] = set()
    for edge in sorted(edges, key=_component_edge_sort_key):
        proposed_groups = selected_groups | {edge.source_key, edge.target_key}
        if selected and len(proposed_groups) > MAX_MERMAID_COMPONENTS:
            continue
        selected.append(edge)
        selected_groups = proposed_groups
        if len(selected) >= MAX_MERMAID_ABSTRACT_EDGES:
            break
    return selected


def _component_edge_sort_key(edge: _MermaidEdgeAggregate) -> tuple[float, str, str]:
    type_weight = {
        "routes_to": 6.0,
        "calls": 4.5,
        "imports": 3.5,
        "inherits": 2.8,
        "exports": 1.8,
    }
    score = sum(type_weight.get(edge_type, 1.0) * min(count, 4) for edge_type, count in edge.counts.items())
    if edge.evidence_count:
        score += edge.confidence_total / edge.evidence_count
    return (-score, edge.source_key, edge.target_key)


def _render_component_diagram(
    groups: dict[str, _MermaidGroup],
    edges: list[_MermaidEdgeAggregate],
) -> list[str]:
    aliases = {
        key: f"C{index}"
        for index, key in enumerate(
            sorted(groups, key=lambda key: (groups[key].rank, groups[key].label, key))
        )
    }
    lines = ["graph TD"]
    for key in aliases:
        group = groups[key]
        lines.append(f'  {aliases[key]}["{_mermaid_text(group.label)}"]')
    for edge in edges:
        source_alias = aliases.get(edge.source_key)
        target_alias = aliases.get(edge.target_key)
        if source_alias is None or target_alias is None:
            continue
        label = _edge_label(edge.counts)
        lines.append(f"  {source_alias} -->|{label}| {target_alias}")
    return lines


def _data_flow_diagram(
    groups: dict[str, _MermaidGroup],
    edges: list[_MermaidEdgeAggregate],
) -> list[str]:
    flow_edges = [
        edge
        for edge in sorted(edges, key=_component_edge_sort_key)
        if edge.counts.get("routes_to") or edge.counts.get("calls") or edge.counts.get("imports")
    ][:MAX_MERMAID_SEQUENCE_MESSAGES]
    if len(groups) <= 1 or len(flow_edges) < 2:
        return []

    involved_keys = {edge.source_key for edge in flow_edges} | {edge.target_key for edge in flow_edges}
    aliases = {
        key: f"D{index}"
        for index, key in enumerate(
            sorted(involved_keys, key=lambda key: (groups[key].rank, groups[key].label, key))
        )
        if key in groups
    }
    lines = ["flowchart LR"]
    for key in aliases:
        lines.append(f'  {aliases[key]}["{_mermaid_text(groups[key].label)}"]')
    for edge in flow_edges:
        source_alias = aliases.get(edge.source_key)
        target_alias = aliases.get(edge.target_key)
        label = _sequence_edge_label(edge.counts)
        if source_alias is None or target_alias is None or not label:
            continue
        lines.append(f"  {source_alias} -->|{label}| {target_alias}")
    return lines if len(lines) > 1 else []


def _interaction_sequence_diagram(
    groups: dict[str, _MermaidGroup],
    edges: list[_MermaidEdgeAggregate],
) -> list[str]:
    sequence_edges = [
        edge
        for edge in sorted(edges, key=_component_edge_sort_key)
        if _sequence_edge_label(edge.counts)
    ][:MAX_MERMAID_SEQUENCE_MESSAGES]
    if len(groups) <= 1 or not sequence_edges:
        return []

    involved_keys: list[str] = []
    for edge in sequence_edges:
        for key in (edge.source_key, edge.target_key):
            if key in groups and key not in involved_keys:
                involved_keys.append(key)

    aliases = {key: f"P{index}" for index, key in enumerate(involved_keys)}
    lines = ["sequenceDiagram"]
    for key in involved_keys:
        label = _mermaid_sequence_text(groups[key].label)
        lines.append(f"  participant {aliases[key]} as {label}")
    for edge in sequence_edges:
        source_alias = aliases.get(edge.source_key)
        target_alias = aliases.get(edge.target_key)
        label = _sequence_edge_label(edge.counts)
        if source_alias is None or target_alias is None or not label:
            continue
        arrow = "->>" if _sequence_edge_is_runtime(edge.counts) else "-->>"
        lines.append(f"  {source_alias}{arrow}{target_alias}: {label}")
    return lines if len(lines) > 1 else []


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
            int(node.get("hop") or 0),
            -float(node.get("score") or 0.0),
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
            int(node.get("hop") or 0),
            -float(node.get("score") or 0.0),
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
    metadata = node.get("metadata") if isinstance(node.get("metadata"), dict) else {}
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
    metadata = node.get("metadata") if isinstance(node.get("metadata"), dict) else {}
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


def _community_index(communities: list[dict[str, object]]) -> dict[str, _MermaidGroup]:
    index: dict[str, _MermaidGroup] = {}
    for rank, community in enumerate(communities):
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
    return _mermaid_edge_text(value).replace("{", "(").replace("}", ")")


