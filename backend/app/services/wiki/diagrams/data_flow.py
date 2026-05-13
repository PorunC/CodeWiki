from backend.app.services.wiki.diagrams.components import _component_edge_sort_key
from backend.app.services.wiki.diagrams.models import (
    MAX_MERMAID_SEQUENCE_MESSAGES,
    _MermaidEdgeAggregate,
    _MermaidGroup,
)
from backend.app.services.wiki.diagrams.rendering import _mermaid_text, _sequence_edge_label


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
