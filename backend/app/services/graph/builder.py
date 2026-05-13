from dataclasses import replace

from backend.app.services.ast_parser import AstSymbol
from backend.app.services.graph.call_resolver import (
    build_call_index,
    file_exports,
    resolve_call,
    resolve_type_reference,
)
from backend.app.services.graph.ids import (
    edge_id,
    file_node_id,
    symbol_node_id as make_symbol_node_id,
)
from backend.app.services.graph.import_resolver import add_import_edges
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


class GraphBuilder:
    def build(self, scan: RepoScanResult, symbols: list[AstSymbol]) -> CodeGraph:
        repo_id = scan.repo.id
        node_index: dict[str, CodeGraphNode] = {}
        edge_index: dict[str, CodeGraphEdge] = {}
        file_nodes: dict[str, str] = {}
        directory_nodes: dict[str, str] = {}
        symbol_nodes: dict[str, str] = {}
        symbols_by_file: dict[str, list[AstSymbol]] = {}

        def add_node(node: CodeGraphNode) -> None:
            node_index[node.id] = replace(node, metadata=node_metadata_with_provenance(node))

        def add_edge(
            source_id: str,
            target_id: str,
            edge_type: str,
            *,
            confidence: float = 1.0,
            weight: float = 1.0,
            is_inferred: bool = False,
            metadata: dict[str, object] | None = None,
        ) -> None:
            graph_edge_id = edge_id(repo_id, source_id, target_id, edge_type)
            edge_metadata = with_edge_provenance(
                metadata or {},
                edge_type=edge_type,
                confidence=confidence,
                is_inferred=is_inferred,
            )
            edge_index[graph_edge_id] = CodeGraphEdge(
                id=graph_edge_id,
                repo_id=repo_id,
                source_id=source_id,
                target_id=target_id,
                type=edge_type,
                confidence=confidence,
                weight=weight,
                is_inferred=is_inferred,
                metadata=edge_metadata,
            )

        repo_node_id = f"{repo_id}:repository"
        add_node(repository_node(scan.repo))

        for scanned_file in scan.files:
            current_file_node_id = file_node_id(repo_id, scanned_file.path)
            file_nodes[scanned_file.path] = current_file_node_id
            add_node(file_node(repo_id, scanned_file, current_file_node_id))
            parent_id = ensure_directory_nodes(
                repo_id=repo_id,
                file_path=scanned_file.path,
                repo_node_id=repo_node_id,
                directory_nodes=directory_nodes,
                add_node=add_node,
                add_edge=add_edge,
            )
            add_edge(parent_id, current_file_node_id, "contains")

        for symbol in symbols:
            symbols_by_file.setdefault(symbol.file_path, []).append(symbol)
            if symbol.type == "file":
                continue
            node_id = make_symbol_node_id(repo_id, symbol.id)
            symbol_nodes[symbol.id] = node_id
            add_node(symbol_node(repo_id, symbol, node_id))

        call_index = build_call_index(symbols, symbol_nodes)
        for symbol in symbols:
            if symbol.type == "file":
                add_import_edges(
                    repo_id=repo_id,
                    file_node_id=file_nodes.get(symbol.file_path),
                    from_file_path=symbol.file_path,
                    imports=symbol.imports,
                    file_nodes=file_nodes,
                    add_node=add_node,
                    add_edge=add_edge,
                )
                continue

            symbol_node_id = symbol_nodes.get(symbol.id)
            if not symbol_node_id:
                continue
            parent_node_id = (
                symbol_nodes.get(symbol.parent_id or "")
                if symbol.parent_id
                else file_nodes.get(symbol.file_path)
            )
            if parent_node_id:
                add_edge(parent_node_id, symbol_node_id, "contains")
            if current_file_node_id := file_nodes.get(symbol.file_path):
                add_edge(current_file_node_id, symbol_node_id, "defines")
                if symbol.metadata.get("exported") or symbol.name in file_exports(
                    symbols_by_file.get(symbol.file_path, [])
                ):
                    add_edge(current_file_node_id, symbol_node_id, "exports")

            for base in symbol.bases:
                target_id, inherited_external = resolve_type_reference(
                    base,
                    symbols=symbols,
                    symbol_nodes=symbol_nodes,
                    repo_id=repo_id,
                    add_node=add_node,
                )
                if target_id:
                    add_edge(
                        symbol_node_id,
                        target_id,
                        "inherits",
                        confidence=1.0 if not inherited_external else 0.65,
                        is_inferred=inherited_external,
                        metadata={"base": base},
                    )

            if symbol.type == "endpoint":
                for handler in symbol.calls:
                    target_id, confidence = resolve_call(
                        call=handler,
                        file_path=symbol.file_path,
                        call_index=call_index,
                    )
                    if target_id:
                        add_edge(
                            symbol_node_id,
                            target_id,
                            "routes_to",
                            confidence=confidence,
                            is_inferred=True,
                            metadata={
                                "handler": handler,
                                "route_method": symbol.metadata.get("route_method"),
                                "route_path": symbol.metadata.get("route_path"),
                            },
                        )

        for symbol in symbols:
            source_id = symbol_nodes.get(symbol.id)
            if not source_id:
                continue
            for call in symbol.calls:
                target_id, confidence = resolve_call(
                    call=call,
                    file_path=symbol.file_path,
                    call_index=call_index,
                )
                if target_id and target_id != source_id:
                    add_edge(
                        source_id,
                        target_id,
                        "calls",
                        confidence=confidence,
                        is_inferred=True,
                        metadata={"call": call},
                    )

        return CodeGraph(
            repo_id=repo_id,
            nodes=sorted(node_index.values(), key=lambda node: (node.type, node.file_path, node.name)),
            edges=sorted(edge_index.values(), key=lambda edge: (edge.type, edge.source_id, edge.target_id)),
        )
