from backend.app.services.graph_rag import RetrievalTrace
from backend.app.services.wiki.diagrams.models import (
    ABSTRACT_DIAGRAM_EDGE_TYPES,
    MAX_MERMAID_ABSTRACT_EDGES,
    MAX_MERMAID_COMPONENTS,
    _MermaidEdgeAggregate,
    _MermaidGroup,
)
from backend.app.services.wiki.diagrams.rendering import (
    _abstract_group_for_node,
    _community_index,
    _edge_confidence,
    _edge_endpoint,
    _edge_label,
    _mermaid_text,
)


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
