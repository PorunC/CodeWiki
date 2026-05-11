import hashlib
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
                        "calls": symbol.calls,
                    },
                )
            )

        for symbol in symbols:
            if symbol.type == "file":
                self._add_import_edges(
                    repo_id=repo_id,
                    file_node_id=file_nodes.get(symbol.file_path),
                    imports=symbol.imports,
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
        imports: list[str],
        add_node,
        add_edge,
    ) -> None:
        if not file_node_id:
            return
        for import_name in imports:
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
            add_edge(file_node_id, module_id, "imports", metadata={"import": import_name})

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
