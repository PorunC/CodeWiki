from backend.app.services.wiki.diagrams.components import _component_edge_sort_key
from backend.app.services.wiki.diagrams.models import (
    MAX_MERMAID_SEQUENCE_MESSAGES,
    _MermaidEdgeAggregate,
    _MermaidGroup,
)
from backend.app.services.wiki.diagrams.rendering import (
    _mermaid_sequence_text,
    _sequence_edge_is_runtime,
    _sequence_edge_label,
)


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
