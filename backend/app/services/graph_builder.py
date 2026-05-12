import hashlib
import posixpath
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from backend.app.services.ast_parser import AstSymbol
from backend.app.services.repo_scanner import RepoScanResult, ScannedFile


@dataclass(frozen=True)
class CodeGraphNode:
    id: str
    repo_id: str
    type: str
    name: str
    file_path: str = ""
    start_line: int | None = None
    end_line: int | None = None
    language: str | None = None
    symbol_id: str | None = None
    summary: str | None = None
    hash: str = ""
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class CodeGraphEdge:
    id: str
    repo_id: str
    source_id: str
    target_id: str
    type: str
    confidence: float = 1.0
    weight: float = 1.0
    is_inferred: bool = False
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class CodeGraph:
    repo_id: str
    nodes: list[CodeGraphNode]
    edges: list[CodeGraphEdge]


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
            node_index[node.id] = node

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
            edge_id = _edge_id(repo_id, source_id, target_id, edge_type)
            edge_index[edge_id] = CodeGraphEdge(
                id=edge_id,
                repo_id=repo_id,
                source_id=source_id,
                target_id=target_id,
                type=edge_type,
                confidence=confidence,
                weight=weight,
                is_inferred=is_inferred,
                metadata=metadata or {},
            )

        repo_node_id = f"{repo_id}:repository"
        add_node(
            CodeGraphNode(
                id=repo_node_id,
                repo_id=repo_id,
                type="repository",
                name=scan.repo.name,
                file_path="",
                metadata={"path": scan.repo.path, "source_type": scan.repo.source_type},
            )
        )

        for scanned_file in scan.files:
            file_node_id = _file_node_id(repo_id, scanned_file.path)
            file_nodes[scanned_file.path] = file_node_id
            add_node(_file_node(repo_id, scanned_file, file_node_id))
            parent_id = self._ensure_directories(
                repo_id=repo_id,
                file_path=scanned_file.path,
                repo_node_id=repo_node_id,
                directory_nodes=directory_nodes,
                add_node=add_node,
                add_edge=add_edge,
            )
            add_edge(parent_id, file_node_id, "contains")

        for symbol in symbols:
            symbols_by_file.setdefault(symbol.file_path, []).append(symbol)
            if symbol.type == "file":
                continue
            node_id = _symbol_node_id(repo_id, symbol.id)
            symbol_nodes[symbol.id] = node_id
            add_node(
                CodeGraphNode(
                    id=node_id,
                    repo_id=repo_id,
                    type=symbol.type,
                    name=symbol.name,
                    file_path=symbol.file_path,
                    start_line=symbol.start_line,
                    end_line=symbol.end_line,
                    language=symbol.language,
                    symbol_id=symbol.id,
                    hash=symbol.hash,
                    metadata={
                        "signature": symbol.signature,
                        "docstring": symbol.docstring,
                        "exports": symbol.exports,
                        "bases": symbol.bases,
                        "decorators": symbol.decorators,
                        "calls": symbol.calls,
                        **symbol.metadata,
                    },
                )
            )

        for symbol in symbols:
            if symbol.type == "file":
                self._add_import_edges(
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
            if file_node_id := file_nodes.get(symbol.file_path):
                add_edge(file_node_id, symbol_node_id, "defines")
                if symbol.metadata.get("exported") or symbol.name in self._file_exports(
                    symbols_by_file.get(symbol.file_path, [])
                ):
                    add_edge(file_node_id, symbol_node_id, "exports")

            for base in symbol.bases:
                target_id, inherited_external = self._resolve_type_reference(
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
                    target_id, confidence = self._resolve_call(
                        call=handler,
                        file_path=symbol.file_path,
                        call_index=self._build_call_index(symbols, symbol_nodes),
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

        call_index = self._build_call_index(symbols, symbol_nodes)
        for symbol in symbols:
            source_id = symbol_nodes.get(symbol.id)
            if not source_id:
                continue
            for call in symbol.calls:
                target_id, confidence = self._resolve_call(
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

    def _ensure_directories(
        self,
        *,
        repo_id: str,
        file_path: str,
        repo_node_id: str,
        directory_nodes: dict[str, str],
        add_node,
        add_edge,
    ) -> str:
        parent_id = repo_node_id
        parts = PurePosixPath(file_path).parts[:-1]
        current_parts: list[str] = []
        for part in parts:
            current_parts.append(part)
            directory_path = "/".join(current_parts)
            directory_id = _directory_node_id(repo_id, directory_path)
            if directory_path not in directory_nodes:
                directory_nodes[directory_path] = directory_id
                add_node(
                    CodeGraphNode(
                        id=directory_id,
                        repo_id=repo_id,
                        type="directory",
                        name=part,
                        file_path=directory_path,
                        metadata={"path": directory_path},
                    )
                )
                add_edge(parent_id, directory_id, "contains")
            parent_id = directory_id
        return parent_id

    def _add_import_edges(
        self,
        *,
        repo_id: str,
        file_node_id: str | None,
        from_file_path: str,
        imports: list[str],
        file_nodes: dict[str, str],
        add_node,
        add_edge,
    ) -> None:
        if not file_node_id:
            return
        for import_name in imports:
            local_target_id = _resolve_import_target(
                import_name,
                from_file_path=from_file_path,
                file_nodes=file_nodes,
            )
            if local_target_id:
                add_edge(
                    file_node_id,
                    local_target_id,
                    "imports",
                    metadata={"import": import_name, "resolved": True},
                )
                continue
            module_id = _module_node_id(repo_id, import_name)
            add_node(
                CodeGraphNode(
                    id=module_id,
                    repo_id=repo_id,
                    type="module",
                    name=import_name,
                    metadata={"external": True},
                )
            )
            add_edge(
                file_node_id,
                module_id,
                "imports",
                metadata={"import": import_name, "resolved": False},
            )

    def _build_call_index(
        self,
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

    def _resolve_call(
        self,
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

    def _resolve_type_reference(
        self,
        name: str,
        *,
        symbols: list[AstSymbol],
        symbol_nodes: dict[str, str],
        repo_id: str,
        add_node,
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
        module_id = _module_node_id(repo_id, name)
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

    def _file_exports(self, file_symbols: list[AstSymbol]) -> set[str]:
        exports: set[str] = set()
        for symbol in file_symbols:
            if symbol.type == "file":
                exports.update(symbol.exports)
        return exports


def _file_node(repo_id: str, scanned_file: ScannedFile, node_id: str) -> CodeGraphNode:
    return CodeGraphNode(
        id=node_id,
        repo_id=repo_id,
        type="file",
        name=PurePosixPath(scanned_file.path).name,
        file_path=scanned_file.path,
        start_line=1,
        language=scanned_file.language,
        symbol_id=f"file:{scanned_file.path}",
        hash=scanned_file.sha256,
        metadata={
            "absolute_path": scanned_file.absolute_path,
            "is_source": scanned_file.is_source,
            "size_bytes": scanned_file.size_bytes,
            "modified_at": scanned_file.modified_at,
        },
    )


def _file_node_id(repo_id: str, file_path: str) -> str:
    return f"{repo_id}:file:{file_path}"


def _directory_node_id(repo_id: str, directory_path: str) -> str:
    return f"{repo_id}:dir:{directory_path}"


def _symbol_node_id(repo_id: str, symbol_id: str) -> str:
    return f"{repo_id}:symbol:{symbol_id}"


def _module_node_id(repo_id: str, import_name: str) -> str:
    return f"{repo_id}:module:{import_name}"


def _edge_id(repo_id: str, source_id: str, target_id: str, edge_type: str) -> str:
    digest = hashlib.sha1(f"{source_id}|{edge_type}|{target_id}".encode("utf-8")).hexdigest()[:20]
    return f"{repo_id}:edge:{digest}"


def _resolve_import_target(
    import_name: str,
    *,
    from_file_path: str,
    file_nodes: dict[str, str],
) -> str | None:
    for candidate in _import_candidates(import_name, from_file_path=from_file_path):
        if candidate in file_nodes:
            return file_nodes[candidate]
    return None


def _import_candidates(import_name: str, *, from_file_path: str) -> list[str]:
    candidates: list[str] = []
    from_dir = PurePosixPath(from_file_path).parent.as_posix()
    from_dir = "" if from_dir == "." else from_dir

    if import_name.startswith("."):
        if import_name.startswith("./") or import_name.startswith("../"):
            base = from_dir
            module_path = posixpath.normpath(posixpath.join(base, import_name))
            candidates.extend(_file_candidates(module_path))
        else:
            leading_dots = len(import_name) - len(import_name.lstrip("."))
            rest = import_name[leading_dots:].replace(".", "/")
            parts = [] if from_dir == "" else from_dir.split("/")
            parent = "/".join(parts[: max(len(parts) - leading_dots + 1, 0)])
            module_path = posixpath.normpath(posixpath.join(parent, rest))
            candidates.extend(_file_candidates(module_path))
    else:
        parts = import_name.split(".")
        for index in range(len(parts), 0, -1):
            candidates.extend(_file_candidates("/".join(parts[:index])))

    return [candidate for candidate in candidates if candidate and not candidate.startswith("../")]


def _file_candidates(module_path: str) -> list[str]:
    module_path = module_path.removesuffix("/")
    suffixes = ["", ".ts", ".tsx", ".js", ".jsx", ".py", "/index.ts", "/index.tsx", "/index.js", "/__init__.py"]
    candidates = []
    for suffix in suffixes:
        candidate = f"{module_path}{suffix}"
        if candidate not in candidates:
            candidates.append(candidate)
    return candidates
