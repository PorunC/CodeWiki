from collections.abc import Callable, Mapping

from backend.app.services.ast_parser import AstSymbol
from backend.app.services.graph.confidence import EdgeResolution, edge_resolution
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
) -> EdgeResolution | None:
    same_file_matches = call_index.get((file_path, call), [])
    if target_id := _single_match(same_file_matches):
        return edge_resolution(target_id, "same_file")
    return resolve_call_with_imports(
        call=call,
        file_path=file_path,
        call_index=call_index,
        import_scopes={},
    )


def resolve_call_with_imports(
    *,
    call: str,
    file_path: str,
    call_index: dict[tuple[str | None, str], list[str]],
    import_scopes: Mapping[str, set[str]],
) -> EdgeResolution | None:
    same_file_matches = call_index.get((file_path, call), [])
    if target_id := _single_match(same_file_matches):
        return edge_resolution(target_id, "same_file")

    import_matches: list[str] = []
    for imported_file in sorted(import_scopes.get(file_path, set())):
        import_matches.extend(call_index.get((imported_file, call), []))
    if target_id := _single_match(import_matches):
        return edge_resolution(target_id, "import_scoped")

    repo_matches = call_index.get((None, call), [])
    if target_id := _single_match(repo_matches):
        return edge_resolution(target_id, "global", is_inferred=True)
    return None


def resolve_type_reference(
    name: str,
    *,
    file_path: str,
    symbols: list[AstSymbol],
    symbol_nodes: dict[str, str],
    repo_id: str,
    add_node: Callable[[CodeGraphNode], None],
    import_scopes: Mapping[str, set[str]],
) -> EdgeResolution | None:
    candidate_symbols = [
        symbol
        for symbol in symbols
        if symbol.type in {"class", "schema", "interface"} and symbol.name == name and symbol.id in symbol_nodes
    ]
    same_file_matches = [symbol_nodes[symbol.id] for symbol in candidate_symbols if symbol.file_path == file_path]
    if target_id := _single_match(same_file_matches):
        return edge_resolution(target_id, "same_file", same_file_reason="same-file")

    import_matches = [
        symbol_nodes[symbol.id]
        for symbol in candidate_symbols
        if symbol.file_path in import_scopes.get(file_path, set())
    ]
    if target_id := _single_match(import_matches):
        return edge_resolution(target_id, "import_scoped")

    global_matches = [symbol_nodes[symbol.id] for symbol in candidate_symbols]
    if target_id := _single_match(global_matches):
        return edge_resolution(target_id, "global", is_inferred=True)

    if candidate_symbols:
        return None
    if not name:
        return None
    return None


def file_exports(file_symbols: list[AstSymbol]) -> set[str]:
    exports: set[str] = set()
    for symbol in file_symbols:
        if symbol.type == "file":
            exports.update(symbol.exports)
    return exports


def _single_match(matches: list[str]) -> str | None:
    unique_matches = set(matches)
    if len(unique_matches) == 1:
        return next(iter(unique_matches))
    return None
