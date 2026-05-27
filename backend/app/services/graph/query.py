from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.app.database import CodeWikiStore
from backend.app.services.graph.affected import (
    file_dependents,
    is_test_file,
    page_source_files,
    transitive_file_dependents,
)
from backend.app.services.graph.models import (
    CodeGraphEdge,
    CodeGraphNode,
    CodeGraphNodeSearchHit,
)

DEFAULT_FLOW_EDGE_TYPES = {"calls", "references", "routes_to"}
IMPACT_EDGE_TYPES = {"calls", "references", "routes_to", "imports", "inherits", "implements", "uses_config"}
CONTAINER_NODE_TYPES = {"repository", "directory", "file", "config", "class", "interface", "schema"}


@dataclass(frozen=True)
class GraphRelationship:
    source: CodeGraphNode
    target: CodeGraphNode
    edge: CodeGraphEdge


@dataclass(frozen=True)
class GraphSubgraphResult:
    root_ids: list[str]
    nodes: list[CodeGraphNode]
    edges: list[CodeGraphEdge]


@dataclass(frozen=True)
class AffectedAnalysisResult:
    repo_id: str
    changed_files: list[str]
    affected_files: list[str]
    affected_tests: list[str]
    affected_wiki_pages: list[str]
    affected_node_ids: list[str]
    traversed_file_count: int


@dataclass(frozen=True)
class ExploreFileSection:
    file_path: str
    language: str | None
    symbols: list[str]
    start_line: int
    end_line: int
    content: str


@dataclass(frozen=True)
class ExploreContextResult:
    repo_id: str
    query: str
    entry_points: list[dict[str, Any]]
    relationships: list[dict[str, Any]]
    source_sections: list[ExploreFileSection]
    additional_files: list[dict[str, Any]]
    text: str
    stats: dict[str, int]


@dataclass(frozen=True)
class GraphTraceStep:
    node: CodeGraphNode
    outgoing_edge: CodeGraphEdge | None


@dataclass(frozen=True)
class GraphTraceResult:
    repo_id: str
    from_symbol: str
    to_symbol: str
    found: bool
    steps: list[GraphTraceStep]
    text: str


@dataclass(frozen=True)
class GraphNodeContextResult:
    repo_id: str
    node: CodeGraphNode
    callers: list[GraphRelationship]
    callees: list[GraphRelationship]
    source_sections: list[ExploreFileSection]
    text: str


class GraphQueryService:
    def __init__(self, *, store: CodeWikiStore) -> None:
        self.store = store

    def search(
        self,
        repo_id: str,
        query: str,
        *,
        types: list[str] | None = None,
        languages: list[str] | None = None,
        path_filters: list[str] | None = None,
        name_filters: list[str] | None = None,
        limit: int = 20,
    ) -> list[CodeGraphNodeSearchHit]:
        self._require_repo(repo_id)
        return self.store.search_code_nodes(
            repo_id,
            query,
            types=types,
            languages=languages,
            path_filters=path_filters,
            name_filters=name_filters,
            limit=limit,
        )

    def callers(self, repo_id: str, symbol: str, *, limit: int = 20) -> list[GraphRelationship]:
        nodes, edges = self._graph(repo_id)
        matches = self._symbol_matches(repo_id, symbol, nodes)
        node_by_id = {node.id: node for node in nodes}
        relationships: list[GraphRelationship] = []
        seen: set[str] = set()
        match_ids = {node.id for node in matches}
        for edge in edges:
            if edge.target_id not in match_ids or edge.type not in DEFAULT_FLOW_EDGE_TYPES:
                continue
            source = node_by_id.get(edge.source_id)
            target = node_by_id.get(edge.target_id)
            if source is None or target is None:
                continue
            key = f"{edge.source_id}->{edge.target_id}:{edge.type}"
            if key in seen:
                continue
            seen.add(key)
            relationships.append(GraphRelationship(source=source, target=target, edge=edge))
        return relationships[: max(1, limit)]

    def callees(self, repo_id: str, symbol: str, *, limit: int = 20) -> list[GraphRelationship]:
        nodes, edges = self._graph(repo_id)
        matches = self._symbol_matches(repo_id, symbol, nodes)
        node_by_id = {node.id: node for node in nodes}
        relationships: list[GraphRelationship] = []
        seen: set[str] = set()
        match_ids = {node.id for node in matches}
        for edge in edges:
            if edge.source_id not in match_ids or edge.type not in DEFAULT_FLOW_EDGE_TYPES:
                continue
            source = node_by_id.get(edge.source_id)
            target = node_by_id.get(edge.target_id)
            if source is None or target is None:
                continue
            key = f"{edge.source_id}->{edge.target_id}:{edge.type}"
            if key in seen:
                continue
            seen.add(key)
            relationships.append(GraphRelationship(source=source, target=target, edge=edge))
        return relationships[: max(1, limit)]

    def impact(self, repo_id: str, symbol: str, *, depth: int = 2) -> GraphSubgraphResult:
        nodes, edges = self._graph(repo_id)
        roots = self._symbol_matches(repo_id, symbol, nodes)
        return self._impact_from_roots(nodes, edges, [node.id for node in roots], depth=max(1, depth))

    def trace(
        self,
        repo_id: str,
        from_symbol: str,
        to_symbol: str,
        *,
        max_depth: int = 8,
    ) -> GraphTraceResult:
        nodes, edges = self._graph(repo_id)
        start_nodes = self._symbol_matches(repo_id, from_symbol, nodes)
        target_nodes = self._symbol_matches(repo_id, to_symbol, nodes)
        node_by_id = {node.id: node for node in nodes}
        target_ids = {node.id for node in target_nodes}
        adjacency: dict[str, list[CodeGraphEdge]] = {}
        for edge in edges:
            if edge.type in DEFAULT_FLOW_EDGE_TYPES:
                adjacency.setdefault(edge.source_id, []).append(edge)

        queue: deque[tuple[str, str, list[CodeGraphEdge]]] = deque(
            (node.id, node.id, []) for node in start_nodes
        )
        visited = {node.id for node in start_nodes}
        path: list[CodeGraphEdge] | None = None
        path_start_id: str | None = None
        while queue:
            start_id, node_id, edge_path = queue.popleft()
            if node_id in target_ids:
                path = edge_path
                path_start_id = start_id
                break
            if len(edge_path) >= max(1, max_depth):
                continue
            for edge in sorted(adjacency.get(node_id, []), key=_edge_priority):
                if edge.target_id in visited or edge.target_id not in node_by_id:
                    continue
                visited.add(edge.target_id)
                queue.append((start_id, edge.target_id, [*edge_path, edge]))

        steps: list[GraphTraceStep] = []
        if path is not None and path_start_id is not None:
            current_id = path_start_id if not path else path[0].source_id
            if current_id in node_by_id:
                for edge in path:
                    steps.append(GraphTraceStep(node=node_by_id[current_id], outgoing_edge=edge))
                    current_id = edge.target_id
                if current_id in node_by_id:
                    steps.append(GraphTraceStep(node=node_by_id[current_id], outgoing_edge=None))
        text = _format_trace_text(from_symbol, to_symbol, steps)
        return GraphTraceResult(
            repo_id=repo_id,
            from_symbol=from_symbol,
            to_symbol=to_symbol,
            found=bool(steps),
            steps=steps,
            text=text,
        )

    def node_context(
        self,
        repo_id: str,
        symbol: str,
        *,
        include_code: bool = True,
        limit: int = 20,
    ) -> GraphNodeContextResult:
        repo = self._require_repo(repo_id)
        nodes, edges = self._graph(repo_id)
        matches = self._symbol_matches(repo_id, symbol, nodes)
        if not matches:
            raise ValueError(f"Node not found: {symbol}")
        node = matches[0]
        callers = self.callers(repo_id, node.id, limit=limit)
        callees = self.callees(repo_id, node.id, limit=limit)
        sections: list[ExploreFileSection] = []
        if include_code and node.file_path:
            sections = _read_node_sections(Path(repo.path).resolve(), node.file_path, [node])
        text = _format_node_context_text(node, callers, callees, sections)
        return GraphNodeContextResult(
            repo_id=repo_id,
            node=node,
            callers=callers,
            callees=callees,
            source_sections=sections,
            text=text,
        )

    def explore(
        self,
        repo_id: str,
        query: str,
        *,
        max_files: int = 12,
        max_nodes: int = 160,
    ) -> ExploreContextResult:
        repo = self._require_repo(repo_id)
        nodes, edges = self._graph(repo_id)
        node_by_id = {node.id: node for node in nodes}
        entry_hits = self.search(repo_id, query, limit=12)
        entry_ids = [hit.node.id for hit in entry_hits]
        selected_ids = self._expand_from_roots(
            edges,
            entry_ids,
            max_depth=3,
            max_nodes=max_nodes,
        )
        selected_nodes = [node_by_id[node_id] for node_id in selected_ids if node_id in node_by_id]
        selected_edges = [
            edge for edge in edges
            if edge.source_id in selected_ids and edge.target_id in selected_ids
        ]
        source_sections, additional_files = self._source_sections(
            repo_path=repo.path,
            selected_nodes=selected_nodes,
            selected_edges=selected_edges,
            node_by_id=node_by_id,
            entry_ids=set(entry_ids),
            max_files=max(1, min(max_files, 20)),
        )
        relationships = [
            _edge_payload(edge, node_by_id)
            for edge in selected_edges
            if edge.type != "contains" and edge.source_id in node_by_id and edge.target_id in node_by_id
        ][:80]
        entry_points = [_node_payload(hit.node, score=hit.score, reasons=list(hit.reasons)) for hit in entry_hits]
        text = _format_explore_text(query, entry_points, relationships, source_sections, additional_files)
        return ExploreContextResult(
            repo_id=repo_id,
            query=query,
            entry_points=entry_points,
            relationships=relationships,
            source_sections=source_sections,
            additional_files=additional_files,
            text=text,
            stats={
                "entry_point_count": len(entry_points),
                "selected_node_count": len(selected_ids),
                "selected_edge_count": len(selected_edges),
                "source_section_count": len(source_sections),
                "additional_file_count": len(additional_files),
            },
        )

    def affected(
        self,
        repo_id: str,
        file_paths: list[str],
        *,
        depth: int = 5,
        test_glob: str | None = None,
    ) -> AffectedAnalysisResult:
        self._require_repo(repo_id)
        nodes, edges = self._graph(repo_id)
        normalized_files = sorted({path.strip().replace("\\", "/") for path in file_paths if path.strip()})
        dependents_by_file = file_dependents(edges, {node.id: node for node in nodes})
        affected_files = transitive_file_dependents(
            normalized_files,
            dependents_by_file,
            max_depth=max(1, depth),
        )
        affected_file_set = set(affected_files) | set(normalized_files)
        affected_node_ids = sorted(
            node.id for node in nodes if node.file_path in affected_file_set
        )
        affected_tests = sorted(
            file_path for file_path in affected_file_set
            if is_test_file(file_path, test_glob)
        )
        affected_wiki_pages = [
            page.slug
            for page in self.store.list_doc_pages(repo_id, language_code=None)
            if page_source_files(page.source_refs) & affected_file_set
            or set(page.graph_refs) & set(affected_node_ids)
        ]
        return AffectedAnalysisResult(
            repo_id=repo_id,
            changed_files=normalized_files,
            affected_files=sorted(affected_file_set),
            affected_tests=affected_tests,
            affected_wiki_pages=sorted(set(affected_wiki_pages)),
            affected_node_ids=affected_node_ids,
            traversed_file_count=len(affected_files),
        )

    def _require_repo(self, repo_id: str):
        repo = self.store.get_repo(repo_id)
        if repo is None:
            raise ValueError(f"Repository not found: {repo_id}")
        return repo

    def _graph(self, repo_id: str) -> tuple[list[CodeGraphNode], list[CodeGraphEdge]]:
        self._require_repo(repo_id)
        nodes, edges = self.store.get_graph(repo_id)
        if not nodes:
            raise ValueError("Run analysis before graph queries.")
        return nodes, edges

    def _symbol_matches(
        self,
        repo_id: str,
        symbol: str,
        nodes: list[CodeGraphNode],
    ) -> list[CodeGraphNode]:
        symbol = symbol.strip()
        if not symbol:
            return []
        hits = self.search(repo_id, symbol, limit=50)
        exact = [hit.node for hit in hits if _matches_symbol(hit.node, symbol)]
        if exact:
            return exact
        if hits:
            return [hits[0].node]
        symbol_lower = symbol.lower()
        return [
            node for node in nodes
            if node.id.lower() == symbol_lower
            or node.name.lower() == symbol_lower
            or (node.symbol_id and symbol_lower in node.symbol_id.lower())
        ][:50]

    def _impact_from_roots(
        self,
        nodes: list[CodeGraphNode],
        edges: list[CodeGraphEdge],
        root_ids: list[str],
        *,
        depth: int,
    ) -> GraphSubgraphResult:
        node_by_id = {node.id: node for node in nodes}
        incoming: dict[str, list[CodeGraphEdge]] = {}
        outgoing_contains: dict[str, list[CodeGraphEdge]] = {}
        for edge in edges:
            incoming.setdefault(edge.target_id, []).append(edge)
            if edge.type == "contains":
                outgoing_contains.setdefault(edge.source_id, []).append(edge)

        selected_ids = set(root_ids)
        selected_edges: dict[str, CodeGraphEdge] = {}
        queue: deque[tuple[str, int]] = deque((node_id, 0) for node_id in root_ids)
        seen: set[tuple[str, int]] = set()
        while queue:
            node_id, current_depth = queue.popleft()
            marker = (node_id, current_depth)
            if marker in seen or current_depth > depth:
                continue
            seen.add(marker)
            node = node_by_id.get(node_id)
            if node and node.type in CONTAINER_NODE_TYPES:
                for edge in outgoing_contains.get(node_id, []):
                    if edge.target_id not in selected_ids:
                        selected_ids.add(edge.target_id)
                        selected_edges[edge.id] = edge
                        queue.append((edge.target_id, current_depth))
            if current_depth >= depth:
                continue
            for edge in incoming.get(node_id, []):
                if edge.type not in IMPACT_EDGE_TYPES and edge.type != "contains":
                    continue
                if edge.source_id not in selected_ids:
                    selected_ids.add(edge.source_id)
                    queue.append((edge.source_id, current_depth + 1))
                selected_edges[edge.id] = edge
        return GraphSubgraphResult(
            root_ids=root_ids,
            nodes=[node_by_id[node_id] for node_id in selected_ids if node_id in node_by_id],
            edges=list(selected_edges.values()),
        )

    def _expand_from_roots(
        self,
        edges: list[CodeGraphEdge],
        root_ids: list[str],
        *,
        max_depth: int,
        max_nodes: int,
    ) -> set[str]:
        adjacency: dict[str, list[CodeGraphEdge]] = {}
        for edge in edges:
            adjacency.setdefault(edge.source_id, []).append(edge)
            adjacency.setdefault(edge.target_id, []).append(edge)
        selected = set(root_ids)
        queue: deque[tuple[str, int]] = deque((node_id, 0) for node_id in root_ids)
        while queue and len(selected) < max_nodes:
            node_id, depth = queue.popleft()
            if depth >= max_depth:
                continue
            adjacent_edges = sorted(adjacency.get(node_id, []), key=_edge_priority)
            for edge in adjacent_edges:
                neighbor_id = edge.target_id if edge.source_id == node_id else edge.source_id
                if neighbor_id in selected:
                    continue
                selected.add(neighbor_id)
                queue.append((neighbor_id, depth + 1))
                if len(selected) >= max_nodes:
                    break
        return selected

    def _source_sections(
        self,
        *,
        repo_path: str,
        selected_nodes: list[CodeGraphNode],
        selected_edges: list[CodeGraphEdge],
        node_by_id: dict[str, CodeGraphNode],
        entry_ids: set[str],
        max_files: int,
    ) -> tuple[list[ExploreFileSection], list[dict[str, Any]]]:
        groups: dict[str, dict[str, Any]] = {}
        for node in selected_nodes:
            if not node.file_path or node.type in {"repository", "directory", "module"}:
                continue
            group = groups.setdefault(node.file_path, {"nodes": [], "score": 0})
            group["nodes"].append(node)
            group["score"] += 8 if node.id in entry_ids else 2 if node.type != "file" else 1
        for edge in selected_edges:
            source = node_by_id.get(edge.source_id)
            if source and source.file_path in groups and edge.type != "contains":
                groups[source.file_path]["score"] += 1

        sorted_groups = sorted(
            groups.items(),
            key=lambda item: (
                is_test_file(item[0], None),
                -int(item[1]["score"]),
                item[0],
            ),
        )
        root = Path(repo_path).resolve()
        sections: list[ExploreFileSection] = []
        additional: list[dict[str, Any]] = []
        for index, (file_path, group) in enumerate(sorted_groups):
            nodes = sorted(group["nodes"], key=lambda node: node.start_line or 1)
            if index >= max_files:
                additional.append(_additional_file_payload(file_path, nodes))
                continue
            file_sections = _read_node_sections(root, file_path, nodes)
            if not file_sections:
                continue
            sections.extend(file_sections)
        return sections, additional[:24]


def _node_payload(
    node: CodeGraphNode,
    *,
    score: float = 0.0,
    reasons: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": node.id,
        "type": node.type,
        "name": node.name,
        "file_path": node.file_path,
        "start_line": node.start_line,
        "end_line": node.end_line,
        "language": node.language,
        "symbol_id": node.symbol_id,
        "score": score,
        "reasons": reasons or [],
    }


def _edge_payload(edge: CodeGraphEdge, node_by_id: dict[str, CodeGraphNode]) -> dict[str, Any]:
    source = node_by_id[edge.source_id]
    target = node_by_id[edge.target_id]
    return {
        "id": edge.id,
        "type": edge.type,
        "source": source.id,
        "target": target.id,
        "source_name": source.name,
        "target_name": target.name,
        "source_file": source.file_path,
        "target_file": target.file_path,
        "confidence": edge.confidence,
        "reason": edge.metadata.get("reason"),
    }


def _matches_symbol(node: CodeGraphNode, symbol: str) -> bool:
    symbol_lower = symbol.lower()
    if node.id.lower() == symbol_lower:
        return True
    if node.name.lower() == symbol_lower:
        return True
    if node.type == "file" and node.name.rsplit(".", 1)[0].lower() == symbol_lower:
        return True
    if node.symbol_id:
        symbol_id_lower = node.symbol_id.lower()
        qualified = symbol.replace(".", "::").lower()
        return symbol_id_lower.endswith(qualified) or qualified in symbol_id_lower
    return False


def _edge_priority(edge: CodeGraphEdge) -> tuple[int, float, str]:
    priority = {
        "contains": 0,
        "defines": 1,
        "routes_to": 2,
        "calls": 3,
        "references": 4,
        "imports": 5,
        "inherits": 6,
        "implements": 6,
    }.get(edge.type, 9)
    return priority, -edge.confidence, edge.id


def _read_node_sections(
    root: Path,
    file_path: str,
    nodes: list[CodeGraphNode],
) -> list[ExploreFileSection]:
    absolute = (root / file_path).resolve()
    if not absolute.is_file() or not absolute.is_relative_to(root):
        return []
    lines = absolute.read_text(encoding="utf-8", errors="replace").splitlines()
    if not lines:
        return []
    ranges: list[tuple[int, int, str]] = []
    for node in nodes:
        if not node.start_line:
            continue
        start = max(1, node.start_line)
        end = max(start, node.end_line or start)
        if node.type in {"file", "config"} and end >= len(lines):
            continue
        ranges.append((start, min(end, len(lines)), f"{node.name}({node.type})"))
    if not ranges:
        ranges.append((1, min(len(lines), 80), file_path))
    ranges.sort()
    clusters: list[tuple[int, int, list[str]]] = []
    for start, end, label in ranges:
        if clusters and start <= clusters[-1][1] + 15:
            prev_start, prev_end, labels = clusters[-1]
            labels.append(label)
            clusters[-1] = (prev_start, max(prev_end, end), labels)
        else:
            clusters.append((start, end, [label]))
    sections: list[ExploreFileSection] = []
    for start, end, labels in clusters[:4]:
        padded_start = max(1, start - 3)
        padded_end = min(len(lines), end + 3)
        content = "\n".join(
            f"{line_number}: {lines[line_number - 1]}"
            for line_number in range(padded_start, padded_end + 1)
        )
        sections.append(
            ExploreFileSection(
                file_path=file_path,
                language=nodes[0].language if nodes else None,
                symbols=sorted(set(labels)),
                start_line=padded_start,
                end_line=padded_end,
                content=content,
            )
        )
    return sections


def _additional_file_payload(file_path: str, nodes: list[CodeGraphNode]) -> dict[str, Any]:
    return {
        "file_path": file_path,
        "symbols": [
            {"name": node.name, "type": node.type, "start_line": node.start_line}
            for node in nodes[:16]
        ],
    }


def _format_explore_text(
    query: str,
    entry_points: list[dict[str, Any]],
    relationships: list[dict[str, Any]],
    sections: list[ExploreFileSection],
    additional_files: list[dict[str, Any]],
) -> str:
    parts = [f"## Exploration: {query}", "", "### Entry Points"]
    for entry in entry_points[:12]:
        location = f"{entry.get('file_path') or ''}:{entry.get('start_line') or ''}".strip(":")
        parts.append(f"- {entry['name']} ({entry['type']}) {location}")
    if relationships:
        parts.extend(["", "### Relationships"])
        for rel in relationships[:40]:
            parts.append(f"- {rel['source_name']} -[{rel['type']}]-> {rel['target_name']}")
    if sections:
        parts.extend(["", "### Source Sections"])
        for section in sections:
            parts.append("")
            parts.append(
                f"#### {section.file_path}:{section.start_line}-{section.end_line} "
                f"({', '.join(section.symbols)})"
            )
            parts.append("```")
            parts.append(section.content)
            parts.append("```")
    if additional_files:
        parts.extend(["", "### Additional Relevant Files"])
        for item in additional_files[:12]:
            symbols = ", ".join(
                f"{symbol['name']}:{symbol.get('start_line') or ''}"
                for symbol in item["symbols"][:8]
            )
            parts.append(f"- {item['file_path']}: {symbols}")
    return "\n".join(parts).strip()


def _format_trace_text(
    from_symbol: str,
    to_symbol: str,
    steps: list[GraphTraceStep],
) -> str:
    if not steps:
        return f"No static call/reference path found from {from_symbol!r} to {to_symbol!r}."
    parts = [f"## Trace: {from_symbol} -> {to_symbol}", ""]
    for index, step in enumerate(steps, start=1):
        node = step.node
        location = f"{node.file_path}:{node.start_line}" if node.file_path else node.id
        parts.append(f"{index}. {node.name} ({node.type}) {location}")
        if step.outgoing_edge is not None:
            parts.append(f"   -> {step.outgoing_edge.type}")
    return "\n".join(parts)


def _format_node_context_text(
    node: CodeGraphNode,
    callers: list[GraphRelationship],
    callees: list[GraphRelationship],
    sections: list[ExploreFileSection],
) -> str:
    location = f"{node.file_path}:{node.start_line}" if node.file_path else node.id
    parts = [f"## Node: {node.name}", "", f"- Type: {node.type}", f"- Location: {location}"]
    if node.symbol_id:
        parts.append(f"- Symbol: {node.symbol_id}")
    if callers:
        parts.extend(["", "### Callers"])
        for rel in callers[:20]:
            source_location = (
                f"{rel.source.file_path}:{rel.source.start_line}" if rel.source.file_path else rel.source.id
            )
            parts.append(f"- {rel.source.name} ({rel.source.type}) {source_location}")
    if callees:
        parts.extend(["", "### Callees"])
        for rel in callees[:20]:
            target_location = (
                f"{rel.target.file_path}:{rel.target.start_line}" if rel.target.file_path else rel.target.id
            )
            parts.append(f"- {rel.target.name} ({rel.target.type}) {target_location}")
    if sections:
        parts.extend(["", "### Source"])
        for section in sections:
            parts.append(f"#### {section.file_path}:{section.start_line}-{section.end_line}")
            parts.append("```")
            parts.append(section.content)
            parts.append("```")
    return "\n".join(parts)

