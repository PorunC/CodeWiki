from backend.app.services.ast_parser import AstSymbol
from backend.app.services.graph import CodeGraphEdge, CodeGraphNode


def _symbols_from_existing_graph(
    nodes: list[CodeGraphNode],
    edges: list[CodeGraphEdge],
    file_paths: set[str],
) -> list[AstSymbol]:
    node_by_id = {node.id: node for node in nodes}
    file_imports: dict[str, set[str]] = {}
    file_exports: dict[str, set[str]] = {}
    parent_symbol_by_node_id: dict[str, str] = {}

    for edge in edges:
        source = node_by_id.get(edge.source_id)
        target = node_by_id.get(edge.target_id)
        if source is None or target is None:
            continue
        if edge.type == "imports" and source.type == "file" and source.file_path in file_paths:
            import_name = edge.metadata.get("import")
            if isinstance(import_name, str) and import_name:
                file_imports.setdefault(source.file_path, set()).add(import_name)
        elif edge.type == "exports" and source.type == "file" and source.file_path in file_paths:
            file_exports.setdefault(source.file_path, set()).add(target.name)
        elif edge.type == "contains" and source.symbol_id and target.symbol_id:
            parent_symbol_by_node_id[target.id] = source.symbol_id

    symbols: list[AstSymbol] = []
    for node in nodes:
        if node.file_path not in file_paths:
            continue
        if node.type == "file":
            symbols.append(
                AstSymbol(
                    id=node.symbol_id or f"file:{node.file_path}",
                    type="file",
                    name=node.name,
                    file_path=node.file_path,
                    language=node.language or "",
                    start_line=node.start_line or 1,
                    end_line=node.end_line or 1,
                    imports=sorted(file_imports.get(node.file_path, set())),
                    exports=sorted(file_exports.get(node.file_path, set())),
                    hash=node.hash,
                )
            )
            continue
        if node.type not in {"class", "function", "method", "interface", "schema", "endpoint"}:
            continue
        symbols.append(
            AstSymbol(
                id=node.symbol_id or f"{node.file_path}::{node.name}",
                type=node.type,
                name=node.name,
                file_path=node.file_path,
                language=node.language or "",
                start_line=node.start_line or 1,
                end_line=node.end_line or node.start_line or 1,
                parent_id=parent_symbol_by_node_id.get(node.id),
                signature=_string_or_none(node.metadata.get("signature")),
                docstring=_string_or_none(node.metadata.get("docstring")),
                exports=_string_list(node.metadata.get("exports")),
                bases=_string_list(node.metadata.get("bases")),
                decorators=_string_list(node.metadata.get("decorators")),
                calls=_string_list(node.metadata.get("calls")),
                hash=node.hash,
                metadata=dict(node.metadata),
            )
        )
    return symbols


def _string_or_none(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item is not None]
