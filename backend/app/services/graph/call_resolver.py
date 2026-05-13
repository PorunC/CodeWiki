from collections.abc import Callable

from backend.app.services.ast_parser import AstSymbol
from backend.app.services.graph.ids import module_node_id
from backend.app.services.graph.models import CodeGraphNode


def build_call_index(
    symbols: list[AstSymbol],
    symbol_nodes: dict[str, str],
) -> dict[tuple[str | None, str], list[str]]:
    index: dict[tuple[str | None, str], list[str]] = {}
    for symbol in symbols:
        if symbol.type == "file":
            continue
        node_id = symbol_nodes.get(symbol.id)
        if not node_id:
            continue
        index.setdefault((symbol.file_path, symbol.name), []).append(node_id)
        index.setdefault((None, symbol.name), []).append(node_id)
    return index


def resolve_call(
    *,
    call: str,
    file_path: str,
    call_index: dict[tuple[str | None, str], list[str]],
) -> tuple[str | None, float]:
    same_file_matches = call_index.get((file_path, call), [])
    if len(same_file_matches) == 1:
        return same_file_matches[0], 0.85
    repo_matches = call_index.get((None, call), [])
    if len(repo_matches) == 1:
        return repo_matches[0], 0.55
    return None, 0.0


def resolve_type_reference(
    name: str,
    *,
    symbols: list[AstSymbol],
    symbol_nodes: dict[str, str],
    repo_id: str,
    add_node: Callable[[CodeGraphNode], None],
) -> tuple[str | None, bool]:
    local_matches = [
        symbol_nodes[symbol.id]
        for symbol in symbols
        if symbol.type in {"class", "schema", "interface"} and symbol.name == name and symbol.id in symbol_nodes
    ]
    if len(local_matches) == 1:
        return local_matches[0], False
    if not name:
        return None, False
    module_id = module_node_id(repo_id, name)
    add_node(
        CodeGraphNode(
            id=module_id,
            repo_id=repo_id,
            type="module",
            name=name,
            metadata={"external": True, "kind": "type_reference"},
        )
    )
    return module_id, True


def file_exports(file_symbols: list[AstSymbol]) -> set[str]:
    exports: set[str] = set()
    for symbol in file_symbols:
        if symbol.type == "file":
            exports.update(symbol.exports)
    return exports
