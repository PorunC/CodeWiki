from typing import Any

from backend.app.services.graph_rag import RetrievalTrace
from backend.app.services.wiki.diagrams.components import (
    _abstract_component_diagram,
    _component_groups_and_edges,
)
from backend.app.services.wiki.diagrams.data_flow import _data_flow_diagram
from backend.app.services.wiki.diagrams.data_model import _data_model_diagram, _key_surface_diagram
from backend.app.services.wiki.diagrams.models import (
    ABSTRACT_DIAGRAM_EDGE_TYPES,
    EDGE_LABEL_ORDER,
    MAX_MERMAID_ABSTRACT_EDGES,
    MAX_MERMAID_CLASS_FIELDS,
    MAX_MERMAID_CLASS_NODES,
    MAX_MERMAID_COMPONENTS,
    MAX_MERMAID_DIAGRAMS,
    MAX_MERMAID_EDGES,
    MAX_MERMAID_SEQUENCE_MESSAGES,
    MAX_MERMAID_SURFACES,
    SOURCE_EDGE_TYPES,
    SURFACE_NODE_TYPES,
    _MermaidEdgeAggregate,
    _MermaidGroup,
)
from backend.app.services.wiki.diagrams.rendering import (
    _abstract_group_for_node,
    _community_index,
    _component_label,
    _edge_confidence,
    _edge_endpoint,
    _edge_label,
    _graph_refs_from_trace,
    _mermaid_class_text,
    _mermaid_edge_text,
    _mermaid_label,
    _mermaid_sequence_text,
    _mermaid_text,
    _section_sources_line,
    _sequence_edge_is_runtime,
    _sequence_edge_label,
    _string_list,
)
from backend.app.services.wiki.diagrams.sequence import _interaction_sequence_diagram


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


__all__ = [
    "ABSTRACT_DIAGRAM_EDGE_TYPES",
    "EDGE_LABEL_ORDER",
    "MAX_MERMAID_ABSTRACT_EDGES",
    "MAX_MERMAID_CLASS_FIELDS",
    "MAX_MERMAID_CLASS_NODES",
    "MAX_MERMAID_COMPONENTS",
    "MAX_MERMAID_DIAGRAMS",
    "MAX_MERMAID_EDGES",
    "MAX_MERMAID_SEQUENCE_MESSAGES",
    "MAX_MERMAID_SURFACES",
    "SOURCE_EDGE_TYPES",
    "SURFACE_NODE_TYPES",
    "_MermaidEdgeAggregate",
    "_MermaidGroup",
    "_abstract_component_diagram",
    "_abstract_group_for_node",
    "_community_index",
    "_component_groups_and_edges",
    "_component_label",
    "_data_flow_diagram",
    "_data_model_diagram",
    "_edge_confidence",
    "_edge_endpoint",
    "_edge_label",
    "_graph_refs_from_trace",
    "_interaction_sequence_diagram",
    "_key_surface_diagram",
    "_mermaid_class_text",
    "_mermaid_edge_text",
    "_mermaid_from_trace",
    "_mermaid_label",
    "_mermaid_sequence_text",
    "_mermaid_text",
    "_section_sources_line",
    "_sequence_edge_is_runtime",
    "_sequence_edge_label",
    "_string_list",
]
