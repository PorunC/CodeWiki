from typing import Any

from backend.app.services.graphrag import RetrievalTrace
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
    MAX_MERMAID_SYMBOL_FLOW_EDGES,
    MAX_MERMAID_SYMBOL_FLOW_NODES,
    MermaidDiagram,
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
from backend.app.services.wiki.diagrams.symbol_flow import _symbol_flow_diagram


def _mermaid_from_trace(
    trace: RetrievalTrace,
    *,
    title: str | None = None,
    source_refs: list[dict[str, Any]] | None = None,
) -> str:
    diagrams = _mermaid_diagrams_from_trace(trace, title=title, source_refs=source_refs)
    if not diagrams:
        return ""

    lines = ["## Diagrams"]
    for diagram in diagrams:
        lines.extend(["", f"### {diagram.title}", "", "```mermaid"])
        lines.extend(diagram.lines)
        lines.append("```")
        if diagram.reason:
            lines.extend(["", f"Diagram rationale: {diagram.reason}"])
    source_line = _section_sources_line(source_refs or [])
    if source_line:
        lines.extend(["", source_line])
    return "\n".join(lines)


def _mermaid_diagrams_from_trace(
    trace: RetrievalTrace,
    *,
    title: str | None = None,
    source_refs: list[dict[str, Any]] | None = None,
) -> list[MermaidDiagram]:
    nodes = {
        str(node["id"]): node
        for node in [*trace.seed_nodes, *trace.expanded_nodes]
        if "id" in node
    }
    if not nodes:
        return []

    page_title = _diagram_page_title(title)
    diagrams: list[MermaidDiagram] = []
    component_groups, component_edges = _component_groups_and_edges(trace, nodes)
    component_diagram = _abstract_component_diagram(component_groups, component_edges)
    if component_diagram:
        diagrams.append(
            MermaidDiagram(
                slot="component-relationships",
                kind="component",
                title=_diagram_title(page_title, "component relationships"),
                heading_hint="System Context",
                reason="Shows the strongest verified dependencies between retrieved components.",
                lines=component_diagram,
                source_edge_ids=_edge_ids(component_edges),
            )
        )

    data_flow_diagram = _data_flow_diagram(component_groups, component_edges)
    if data_flow_diagram:
        diagrams.append(
            MermaidDiagram(
                slot="data-flow",
                kind="data_flow",
                title=_diagram_title(page_title, "data and call flow"),
                heading_hint="Control Flow",
                reason="Highlights runtime-like calls, routes, and imports selected from graph evidence.",
                lines=data_flow_diagram,
                source_edge_ids=_edge_ids(component_edges),
            )
        )

    symbol_flow_diagram = _symbol_flow_diagram(trace, nodes)
    if symbol_flow_diagram:
        diagrams.append(
            MermaidDiagram(
                slot="implementation-flow",
                kind="symbol_flow",
                title=_diagram_title(page_title, "implementation flow"),
                heading_hint="Control Flow",
                reason=(
                    "Shows concrete endpoints, functions, methods, classes, imports, and "
                    "configuration links selected from graph evidence."
                ),
                lines=symbol_flow_diagram.lines,
                source_edge_ids=symbol_flow_diagram.edge_ids,
            )
        )

    sequence_diagram = _interaction_sequence_diagram(component_groups, component_edges)
    if sequence_diagram:
        diagrams.append(
            MermaidDiagram(
                slot="interaction-sequence",
                kind="sequence",
                title=_diagram_title(page_title, "interaction sequence"),
                heading_hint="Control Flow",
                reason="Orders the most relevant interactions as a compact sequence.",
                lines=sequence_diagram,
                source_edge_ids=_edge_ids(component_edges),
            )
        )

    data_diagram = _data_model_diagram(trace, nodes)
    if data_diagram:
        diagrams.append(
            MermaidDiagram(
                slot="data-model",
                kind="data_model",
                title=_diagram_title(page_title, "data model"),
                heading_hint="Data Model",
                reason="Uses retrieved classes, schemas, and interfaces rather than inferred models.",
                lines=data_diagram,
                source_edge_ids=_edge_ids_for_types(trace, {"inherits"}),
            )
        )

    surface_diagram = _key_surface_diagram(trace, nodes)
    if surface_diagram:
        diagrams.append(
            MermaidDiagram(
                slot="api-surfaces",
                kind="surface",
                title=_diagram_title(page_title, "public surfaces"),
                heading_hint="API Surface",
                reason="Maps endpoints, classes, schemas, and interfaces to their owning components.",
                lines=surface_diagram,
                source_edge_ids=_edge_ids_for_types(trace, SOURCE_EDGE_TYPES),
            )
        )

    return diagrams[:MAX_MERMAID_DIAGRAMS]


def _diagram_slots_payload(diagrams: list[MermaidDiagram]) -> list[dict[str, object]]:
    return [
        {
            "slot": diagram.slot,
            "placeholder": f"[[DIAGRAM:{diagram.slot}]]",
            "kind": diagram.kind,
            "title": diagram.title,
            "heading_hint": diagram.heading_hint,
            "reason": diagram.reason,
            "source_edge_ids": list(diagram.source_edge_ids),
        }
        for diagram in diagrams
    ]


def _diagram_page_title(title: str | None) -> str:
    normalized = (title or "").strip()
    return normalized if normalized else "Repository"


def _diagram_title(page_title: str, suffix: str) -> str:
    if not page_title:
        return suffix.capitalize()
    return f"{page_title} {suffix}"


def _edge_ids(edges: list[_MermaidEdgeAggregate]) -> tuple[str, ...]:
    ids: list[str] = []
    seen: set[str] = set()
    for edge in edges:
        for edge_id in edge.edge_ids:
            if edge_id not in seen:
                seen.add(edge_id)
                ids.append(edge_id)
    return tuple(ids)


def _edge_ids_for_types(trace: RetrievalTrace, edge_types: set[str]) -> tuple[str, ...]:
    ids: list[str] = []
    for edge in trace.related_edges:
        edge_id = str(edge.get("id") or "")
        if edge_id and str(edge.get("type") or "") in edge_types:
            ids.append(edge_id)
    return tuple(ids)


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
    "MAX_MERMAID_SYMBOL_FLOW_EDGES",
    "MAX_MERMAID_SYMBOL_FLOW_NODES",
    "MermaidDiagram",
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
    "_diagram_slots_payload",
    "_mermaid_class_text",
    "_mermaid_edge_text",
    "_mermaid_diagrams_from_trace",
    "_mermaid_from_trace",
    "_mermaid_label",
    "_mermaid_sequence_text",
    "_mermaid_text",
    "_section_sources_line",
    "_sequence_edge_is_runtime",
    "_sequence_edge_label",
    "_string_list",
    "_symbol_flow_diagram",
]
