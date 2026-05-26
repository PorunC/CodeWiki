from dataclasses import dataclass, field, replace

from backend.app.services.ast_parser import AstSymbol
from backend.app.services.graph.call_resolver import (
    build_call_index,
    file_exports,
    resolve_call_with_imports,
    resolve_type_reference,
)
from backend.app.services.graph.confidence import STRUCTURAL_EDGE_REASONS
from backend.app.services.graph.config_detector import (
    ConfigDetection,
    detect_config_file,
    is_config_reference,
)
from backend.app.services.graph.ids import (
    edge_id,
    file_node_id,
    symbol_node_id as make_symbol_node_id,
)
from backend.app.services.graph.import_resolver import (
    add_import_edges,
    resolve_import_file,
    resolve_import_target,
)
from backend.app.services.graph.models import CodeGraph, CodeGraphEdge, CodeGraphNode
from backend.app.services.graph.node_factory import (
    ensure_directory_nodes,
    file_node,
    node_metadata_with_provenance,
    repository_node,
    symbol_node,
)
from backend.app.services.graph_provenance import with_edge_provenance
from backend.app.services.repo_scanner import RepoScanResult


@dataclass
class _GraphBuildState:
    repo_id: str
    node_index: dict[str, CodeGraphNode] = field(default_factory=dict)
    edge_index: dict[str, CodeGraphEdge] = field(default_factory=dict)
    file_nodes: dict[str, str] = field(default_factory=dict)
    config_nodes: dict[str, str] = field(default_factory=dict)
    config_detection_by_path: dict[str, ConfigDetection] = field(default_factory=dict)
    directory_nodes: dict[str, str] = field(default_factory=dict)
    symbol_nodes: dict[str, str] = field(default_factory=dict)
    symbols_by_file: dict[str, list[AstSymbol]] = field(default_factory=dict)

    def add_node(self, node: CodeGraphNode) -> None:
        self.node_index[node.id] = replace(node, metadata=node_metadata_with_provenance(node))

    def add_edge(
        self,
        source_id: str,
        target_id: str,
        edge_type: str,
        *,
        confidence: float = 1.0,
        weight: float = 1.0,
        is_inferred: bool = False,
        reason: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        graph_edge_id = edge_id(self.repo_id, source_id, target_id, edge_type)
        default_reason = reason or STRUCTURAL_EDGE_REASONS.get(edge_type, edge_type)
        edge_metadata = with_edge_provenance(
            metadata or {},
            edge_type=edge_type,
            confidence=confidence,
            is_inferred=is_inferred,
            reason=default_reason,
        )
        self.edge_index[graph_edge_id] = CodeGraphEdge(
            id=graph_edge_id,
            repo_id=self.repo_id,
            source_id=source_id,
            target_id=target_id,
            type=edge_type,
            confidence=confidence,
            weight=weight,
            is_inferred=is_inferred,
            metadata=edge_metadata,
        )

    def graph(self) -> CodeGraph:
        return CodeGraph(
            repo_id=self.repo_id,
            nodes=sorted(
                self.node_index.values(),
                key=lambda node: (node.type, node.file_path, node.name),
            ),
            edges=sorted(
                self.edge_index.values(),
                key=lambda edge: (edge.type, edge.source_id, edge.target_id),
            ),
        )


class GraphBuilder:
    def build(self, scan: RepoScanResult, symbols: list[AstSymbol]) -> CodeGraph:
        state = _GraphBuildState(repo_id=scan.repo.id)
        self._build_file_nodes(scan, state)
        self._build_symbol_nodes(symbols, state)
        call_index = build_call_index(symbols, state.symbol_nodes)
        import_scopes = import_scopes_for_files(
            {
                symbol.file_path: symbol.imports
                for symbol in symbols
                if symbol.type == "file" and symbol.imports
            },
            file_nodes=state.file_nodes,
        )
        self._build_file_import_edges(symbols, state)
        self._build_symbol_structure_edges(symbols, state, call_index, import_scopes)
        self._build_call_reference_edges(symbols, state, call_index, import_scopes)
        return state.graph()

    def _build_file_nodes(self, scan: RepoScanResult, state: _GraphBuildState) -> None:
        repo_node_id = f"{state.repo_id}:repository"
        state.add_node(repository_node(scan.repo))

        for scanned_file in scan.files:
            current_file_node_id = file_node_id(state.repo_id, scanned_file.path)
            state.file_nodes[scanned_file.path] = current_file_node_id
            config_detection = detect_config_file(scanned_file)
            extra_metadata: dict[str, object] = {}
            node_type = "file"
            if config_detection.is_config:
                node_type = "config"
                state.config_nodes[scanned_file.path] = current_file_node_id
                state.config_detection_by_path[scanned_file.path] = config_detection
                extra_metadata = {
                    "config": True,
                    "config_kind": config_detection.kind,
                    "config_reason": config_detection.reason,
                    "config_confidence": config_detection.confidence,
                }
            state.add_node(
                file_node(
                    state.repo_id,
                    scanned_file,
                    current_file_node_id,
                    node_type=node_type,
                    extra_metadata=extra_metadata,
                )
            )
            parent_id = ensure_directory_nodes(
                repo_id=state.repo_id,
                file_path=scanned_file.path,
                repo_node_id=repo_node_id,
                directory_nodes=state.directory_nodes,
                add_node=state.add_node,
                add_edge=state.add_edge,
            )
            state.add_edge(parent_id, current_file_node_id, "contains")

    def _build_symbol_nodes(self, symbols: list[AstSymbol], state: _GraphBuildState) -> None:
        for symbol in symbols:
            state.symbols_by_file.setdefault(symbol.file_path, []).append(symbol)
            if symbol.type == "file":
                continue
            node_id = make_symbol_node_id(state.repo_id, symbol.id)
            state.symbol_nodes[symbol.id] = node_id
            state.add_node(symbol_node(state.repo_id, symbol, node_id))

    def _build_file_import_edges(self, symbols: list[AstSymbol], state: _GraphBuildState) -> None:
        for symbol in symbols:
            if symbol.type != "file":
                continue
            current_file_id = state.file_nodes.get(symbol.file_path)
            add_import_edges(
                repo_id=state.repo_id,
                file_node_id=current_file_id,
                from_file_path=symbol.file_path,
                imports=symbol.imports,
                file_nodes=state.file_nodes,
                add_node=state.add_node,
                add_edge=state.add_edge,
            )
            for config_target_id in config_targets_for_import(
                symbol.imports,
                from_file_path=symbol.file_path,
                file_nodes=state.file_nodes,
                config_nodes=state.config_nodes,
            ):
                if not current_file_id:
                    continue
                state.add_edge(
                    current_file_id,
                    config_target_id,
                    "uses_config",
                    confidence=0.78,
                    is_inferred=True,
                    reason="config-import",
                    metadata={"imports": symbol.imports},
                )

    def _build_symbol_structure_edges(
        self,
        symbols: list[AstSymbol],
        state: _GraphBuildState,
        call_index: dict[tuple[str | None, str], list[str]],
        import_scopes: dict[str, set[str]],
    ) -> None:
        for symbol in symbols:
            if symbol.type == "file":
                continue
            symbol_node_id = state.symbol_nodes.get(symbol.id)
            if not symbol_node_id:
                continue
            parent_node_id = (
                state.symbol_nodes.get(symbol.parent_id or "")
                if symbol.parent_id
                else state.file_nodes.get(symbol.file_path)
            )
            if parent_node_id:
                state.add_edge(parent_node_id, symbol_node_id, "contains")
            if current_file_node_id := state.file_nodes.get(symbol.file_path):
                state.add_edge(current_file_node_id, symbol_node_id, "defines")
                if symbol.metadata.get("exported") or symbol.name in file_exports(
                    state.symbols_by_file.get(symbol.file_path, [])
                ):
                    state.add_edge(current_file_node_id, symbol_node_id, "exports")

            for base in symbol.bases:
                resolved = resolve_type_reference(
                    base,
                    file_path=symbol.file_path,
                    symbols=symbols,
                    symbol_nodes=state.symbol_nodes,
                    repo_id=state.repo_id,
                    add_node=state.add_node,
                    import_scopes=import_scopes,
                )
                if resolved:
                    state.add_edge(
                        symbol_node_id,
                        resolved.target_id,
                        "inherits",
                        confidence=resolved.confidence,
                        is_inferred=resolved.is_inferred,
                        reason=resolved.reason,
                        metadata={"base": base, "resolution_tier": resolved.tier},
                    )

            for interface in symbol.implements:
                resolved = resolve_type_reference(
                    interface,
                    file_path=symbol.file_path,
                    symbols=symbols,
                    symbol_nodes=state.symbol_nodes,
                    repo_id=state.repo_id,
                    add_node=state.add_node,
                    import_scopes=import_scopes,
                )
                if resolved:
                    state.add_edge(
                        symbol_node_id,
                        resolved.target_id,
                        "implements",
                        confidence=resolved.confidence,
                        is_inferred=resolved.is_inferred,
                        reason=resolved.reason,
                        metadata={"interface": interface, "resolution_tier": resolved.tier},
                    )

            if symbol.type == "endpoint":
                for handler in symbol.calls:
                    resolved = resolve_call_with_imports(
                        call=handler,
                        file_path=symbol.file_path,
                        call_index=call_index,
                        import_scopes=import_scopes,
                    )
                    if resolved:
                        state.add_edge(
                            symbol_node_id,
                            resolved.target_id,
                            "routes_to",
                            confidence=resolved.confidence,
                            is_inferred=True,
                            reason=resolved.reason,
                            metadata={
                                "handler": handler,
                                "route_method": symbol.metadata.get("route_method"),
                                "route_path": symbol.metadata.get("route_path"),
                                "resolution_tier": resolved.tier,
                            },
                        )

    def _build_call_reference_edges(
        self,
        symbols: list[AstSymbol],
        state: _GraphBuildState,
        call_index: dict[tuple[str | None, str], list[str]],
        import_scopes: dict[str, set[str]],
    ) -> None:
        for symbol in symbols:
            source_id = state.symbol_nodes.get(symbol.id)
            if not source_id:
                continue
            for call in symbol.calls:
                resolved = resolve_call_with_imports(
                    call=call,
                    file_path=symbol.file_path,
                    call_index=call_index,
                    import_scopes=import_scopes,
                )
                if resolved and resolved.target_id != source_id:
                    state.add_edge(
                        source_id,
                        resolved.target_id,
                        "calls",
                        confidence=resolved.confidence,
                        is_inferred=True,
                        reason=resolved.reason,
                        metadata={"call": call, "resolution_tier": resolved.tier},
                    )

            for reference in symbol.references:
                if should_skip_reference(symbol, reference):
                    continue
                resolved = resolve_call_with_imports(
                    call=reference,
                    file_path=symbol.file_path,
                    call_index=call_index,
                    import_scopes=import_scopes,
                )
                if resolved and resolved.target_id != source_id:
                    state.add_edge(
                        source_id,
                        resolved.target_id,
                        "references",
                        confidence=resolved.confidence,
                        is_inferred=True,
                        reason=resolved.reason,
                        metadata={"reference": reference, "resolution_tier": resolved.tier},
                    )

            for config_target_id in config_targets_for_references(
                [*symbol.calls, *symbol.references],
                config_nodes=state.config_nodes,
                config_detection_by_path=state.config_detection_by_path,
            ):
                state.add_edge(
                    source_id,
                    config_target_id,
                    "uses_config",
                    confidence=0.58,
                    is_inferred=True,
                    reason="config-reference",
                    metadata={"references": sorted(set([*symbol.calls, *symbol.references]))},
                )


def should_skip_reference(symbol: AstSymbol, reference: str) -> bool:
    if not reference or reference == symbol.name:
        return True
    ignored = {
        *symbol.calls,
        *symbol.bases,
        *symbol.implements,
        *symbol.decorators,
        "self",
        "this",
        "cls",
        "None",
        "True",
        "False",
        "null",
        "undefined",
    }
    return reference in ignored or (not reference[:1].isupper() and is_config_reference(reference))


def import_scopes_for_files(
    file_imports: dict[str, list[str]],
    *,
    file_nodes: dict[str, str],
) -> dict[str, set[str]]:
    scopes: dict[str, set[str]] = {}
    for file_path, imports in file_imports.items():
        for import_name in imports:
            target_file = resolve_import_file(
                import_name,
                from_file_path=file_path,
                file_nodes=file_nodes,
            )
            if target_file:
                scopes.setdefault(file_path, set()).add(target_file)
    return scopes


def config_targets_for_import(
    imports: list[str],
    *,
    from_file_path: str,
    file_nodes: dict[str, str],
    config_nodes: dict[str, str],
) -> set[str]:
    targets: set[str] = set()
    config_node_ids = set(config_nodes.values())
    for import_name in imports:
        target_id = resolve_import_target(
            import_name,
            from_file_path=from_file_path,
            file_nodes=file_nodes,
        )
        if target_id in config_node_ids:
            targets.add(target_id)
            continue
        if is_config_reference(import_name):
            targets.update(match_config_nodes(import_name, config_nodes))
    return targets


def config_targets_for_references(
    references: list[str],
    *,
    config_nodes: dict[str, str],
    config_detection_by_path: dict[str, ConfigDetection],
) -> set[str]:
    targets: set[str] = set()
    for reference in references:
        if reference[:1].isupper() or not is_config_reference(reference):
            continue
        matches = match_config_nodes(reference, config_nodes, config_detection_by_path=config_detection_by_path)
        if matches:
            targets.update(matches)
        elif len(config_nodes) == 1:
            targets.update(config_nodes.values())
    return targets


def match_config_nodes(
    value: str,
    config_nodes: dict[str, str],
    *,
    config_detection_by_path: dict[str, ConfigDetection] | None = None,
) -> set[str]:
    normalized = value.replace("\\", "/").lower()
    matches: set[str] = set()
    for path, node_id in config_nodes.items():
        lower_path = path.lower()
        detection = (config_detection_by_path or {}).get(path)
        if normalized in lower_path or any(part and part in lower_path for part in normalized.split("/")):
            matches.add(node_id)
            continue
        if "env" in normalized and (
            lower_path.endswith(".env") or (detection is not None and detection.kind == "environment")
        ):
            matches.add(node_id)
            continue
        if any(term in normalized for term in ("config", "settings")) and any(
            term in lower_path for term in ("config", "settings")
        ):
            matches.add(node_id)
    return matches
