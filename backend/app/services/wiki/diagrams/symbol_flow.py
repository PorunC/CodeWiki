from dataclasses import dataclass

from backend.app.services.graphrag import RetrievalTrace
from backend.app.services.wiki.diagrams.models import (
    MAX_MERMAID_SYMBOL_FLOW_EDGES,
    MAX_MERMAID_SYMBOL_FLOW_NODES,
)
from backend.app.services.wiki.diagrams.rendering import (
    _edge_confidence,
    _edge_endpoint,
    _mermaid_edge_text,
    _mermaid_text,
)

SYMBOL_FLOW_EDGE_TYPES = {
    "routes_to",
    "calls",
    "imports",
    "uses_config",
    "inherits",
    "implements",
    "references",
}
SYMBOL_FLOW_NODE_TYPES = {
    "endpoint",
    "function",
    "method",
    "class",
    "schema",
    "interface",
    "config",
    "file",
    "module",
}


@dataclass(frozen=True)
class SymbolFlowDiagram:
    lines: list[str]
    edge_ids: tuple[str, ...]


def _symbol_flow_diagram(
    trace: RetrievalTrace,
    nodes: dict[str, dict[str, object]],
) -> SymbolFlowDiagram | None:
    candidates = [
        edge
        for edge in trace.related_edges
        if _is_symbol_flow_edge(edge, nodes)
    ]
    if not candidates:
        return None

    selected_edges: list[dict[str, object]] = []
    selected_node_ids: list[str] = []
    selected_node_set: set[str] = set()
    for edge in sorted(candidates, key=_symbol_flow_edge_sort_key):
        source_id = _edge_endpoint(edge, "source_id", "source")
        target_id = _edge_endpoint(edge, "target_id", "target")
        proposed_node_ids = [
            node_id
            for node_id in (source_id, target_id)
            if node_id and node_id not in selected_node_set
        ]
        if (
            selected_edges
            and len(selected_node_set) + len(proposed_node_ids) > MAX_MERMAID_SYMBOL_FLOW_NODES
        ):
            continue
        for node_id in proposed_node_ids:
            selected_node_set.add(node_id)
            selected_node_ids.append(node_id)
        selected_edges.append(edge)
        if len(selected_edges) >= MAX_MERMAID_SYMBOL_FLOW_EDGES:
            break

    if not selected_edges or len(selected_node_ids) < 2:
        return None

    aliases = {node_id: f"I{index}" for index, node_id in enumerate(selected_node_ids)}
    lines = ["flowchart TD"]
    for node_id in selected_node_ids:
        node = nodes.get(node_id)
        if node is None:
            continue
        lines.append(f'  {aliases[node_id]}["{_symbol_flow_label(node)}"]')

    edge_ids: list[str] = []
    for edge in selected_edges:
        source_alias = aliases.get(_edge_endpoint(edge, "source_id", "source"))
        target_alias = aliases.get(_edge_endpoint(edge, "target_id", "target"))
        if source_alias is None or target_alias is None:
            continue
        label = _mermaid_edge_text(_symbol_flow_edge_label(edge))
        lines.append(f"  {source_alias} -->|{label}| {target_alias}")
        edge_id = str(edge.get("id") or "")
        if edge_id:
            edge_ids.append(edge_id)

    return SymbolFlowDiagram(lines=lines, edge_ids=tuple(edge_ids)) if len(lines) > 1 else None


def _is_symbol_flow_edge(
    edge: dict[str, object],
    nodes: dict[str, dict[str, object]],
) -> bool:
    edge_type = str(edge.get("type") or "")
    if edge_type not in SYMBOL_FLOW_EDGE_TYPES:
        return False
    source_node = nodes.get(_edge_endpoint(edge, "source_id", "source"))
    target_node = nodes.get(_edge_endpoint(edge, "target_id", "target"))
    if source_node is None or target_node is None:
        return False
    return (
        str(source_node.get("type") or "") in SYMBOL_FLOW_NODE_TYPES
        and str(target_node.get("type") or "") in SYMBOL_FLOW_NODE_TYPES
    )


def _symbol_flow_edge_sort_key(edge: dict[str, object]) -> tuple[float, str, str]:
    type_weight = {
        "routes_to": 7.0,
        "calls": 6.0,
        "uses_config": 4.0,
        "imports": 3.5,
        "inherits": 3.2,
        "implements": 3.0,
        "references": 2.0,
    }
    edge_type = str(edge.get("type") or "")
    score = type_weight.get(edge_type, 1.0) + _edge_confidence(edge)
    return (-score, _edge_endpoint(edge, "source_id", "source"), _edge_endpoint(edge, "target_id", "target"))


def _symbol_flow_label(node: dict[str, object]) -> str:
    node_type = str(node.get("type") or "")
    metadata = node.get("metadata") if isinstance(node.get("metadata"), dict) else {}
    if node_type == "endpoint":
        method = str(metadata.get("route_method") or "").upper()
        route_path = str(metadata.get("route_path") or "")
        label = " ".join(part for part in [method, route_path] if part) or str(node.get("name") or "endpoint")
        return _mermaid_text(f"{label}<br/>endpoint")

    name = str(node.get("name") or node.get("id") or node_type)
    file_path = str(node.get("file_path") or "")
    if node_type == "module" and metadata.get("external"):
        return _mermaid_text(f"External<br/>{name}")
    if file_path:
        return _mermaid_text(f"{name} ({node_type})<br/>{file_path}")
    return _mermaid_text(f"{name} ({node_type})")


def _symbol_flow_edge_label(edge: dict[str, object]) -> str:
    edge_type = str(edge.get("type") or "")
    metadata = edge.get("metadata") if isinstance(edge.get("metadata"), dict) else {}
    if edge_type == "routes_to":
        method = str(metadata.get("route_method") or "").upper()
        route_path = str(metadata.get("route_path") or "")
        route = " ".join(part for part in [method, route_path] if part)
        return f"routes to {route}" if route else "routes to"
    if edge_type == "calls" and metadata.get("call"):
        return f"calls {metadata['call']}"
    if edge_type == "imports" and metadata.get("import"):
        return f"imports {metadata['import']}"
    if edge_type == "uses_config":
        return "uses config"
    if edge_type == "inherits" and metadata.get("base"):
        return f"inherits {metadata['base']}"
    if edge_type == "implements" and metadata.get("interface"):
        return f"implements {metadata['interface']}"
    if edge_type == "references" and metadata.get("reference"):
        return f"references {metadata['reference']}"
    return edge_type.replace("_", " ")
