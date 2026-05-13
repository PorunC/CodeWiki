from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.app.database import SQLiteStore, get_store
from backend.app.services.ast_parser import AstParser, AstSymbol
from backend.app.services.community_detector import CommunityDetector
from backend.app.services.graph_builder import CodeGraphEdge, CodeGraphNode, GraphBuilder
from backend.app.services.graph_rag import GraphRAGRetriever
from backend.app.services.repo_scanner import RepoDescriptor, RepoScanResult, RepoScanner, ScannedFile


@dataclass(frozen=True)
class IncrementalUpdatePlan:
    repo_id: str
    changed_files: list[str] = field(default_factory=list)
    new_files: list[str] = field(default_factory=list)
    deleted_files: list[str] = field(default_factory=list)
    unchanged_files: list[str] = field(default_factory=list)

    @property
    def affected_files(self) -> list[str]:
        return sorted({*self.changed_files, *self.new_files, *self.deleted_files})

    def as_dict(self) -> dict[str, object]:
        return {
            "repo_id": self.repo_id,
            "changed_files": self.changed_files,
            "new_files": self.new_files,
            "deleted_files": self.deleted_files,
            "unchanged_files": self.unchanged_files,
            "affected_files": self.affected_files,
        }


@dataclass(frozen=True)
class IncrementalUpdateResult:
    run_id: str
    repo_id: str
    status: str
    plan: IncrementalUpdatePlan
    scanned_count: int
    parsed_file_count: int
    reused_file_count: int
    node_count: int
    edge_count: int
    community_count: int
    chunk_count: int
    stale_pages: list[str] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)

    def stats(self) -> dict[str, Any]:
        return {
            "mode": "incremental",
            "plan": self.plan.as_dict(),
            "scanned_count": self.scanned_count,
            "parsed_file_count": self.parsed_file_count,
            "reused_file_count": self.reused_file_count,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "community_count": self.community_count,
            "chunk_count": self.chunk_count,
            "stale_pages": self.stale_pages,
            "errors": self.errors,
        }


class IncrementalUpdater:
    def __init__(
        self,
        *,
        store: SQLiteStore | None = None,
        scanner: RepoScanner | None = None,
        parser: AstParser | None = None,
        graph_builder: GraphBuilder | None = None,
        community_detector: CommunityDetector | None = None,
        graphrag: GraphRAGRetriever | None = None,
    ) -> None:
        self.store = store or get_store()
        self.scanner = scanner or RepoScanner()
        self.parser = parser or AstParser()
        self.graph_builder = graph_builder or GraphBuilder()
        self.community_detector = community_detector or CommunityDetector()
        self.graphrag = graphrag or GraphRAGRetriever(store=self.store)

    def plan(self, repo_id: str) -> IncrementalUpdatePlan:
        repo = self._repo(repo_id)
        scan = self.scanner.scan(repo.path, name=repo.name, source_type=repo.source_type)
        nodes, _edges = self.store.get_graph(repo_id)
        return _plan_from_scan(repo_id, scan, nodes)

    def update(self, repo_id: str, *, refresh_chunks: bool = True) -> IncrementalUpdateResult:
        repo = self._repo(repo_id)
        scan = self.scanner.scan(repo.path, name=repo.name, source_type=repo.source_type)
        old_nodes, old_edges = self.store.get_graph(repo_id)
        plan = _plan_from_scan(repo_id, scan, old_nodes)
        stale_graph_refs = _affected_graph_refs(old_nodes, old_edges, plan.changed_files + plan.deleted_files)
        run = self.store.create_analysis_run(repo_id)

        try:
            if not plan.affected_files:
                chunk_count = len(self.store.list_code_chunks(repo_id))
                result = IncrementalUpdateResult(
                    run_id=run.id,
                    repo_id=repo_id,
                    status="done",
                    plan=plan,
                    scanned_count=scan.scanned_count,
                    parsed_file_count=0,
                    reused_file_count=len(plan.unchanged_files),
                    node_count=len(old_nodes),
                    edge_count=len(old_edges),
                    community_count=len(self.store.list_graph_communities(repo_id)),
                    chunk_count=chunk_count,
                )
                self.store.finish_analysis_run(run.id, status="done", stats=result.stats())
                return result

            changed_or_new = set(plan.changed_files + plan.new_files)
            reused_symbols = _symbols_from_existing_graph(old_nodes, old_edges, set(plan.unchanged_files))
            parsed_symbols, parse_errors = self._parse_scan(
                scan.files,
                repo_root=Path(scan.repo.path),
                only_paths=changed_or_new,
            )
            graph = self.graph_builder.build(scan, [*reused_symbols, *parsed_symbols])
            self.store.replace_graph(repo_id, nodes=graph.nodes, edges=graph.edges)
            communities = self.community_detector.detect(repo_id, graph.nodes, graph.edges)
            self.store.replace_graph_communities(repo_id, communities.communities)

            chunk_count = len(self.store.list_code_chunks(repo_id))
            if refresh_chunks:
                chunk_count = self._refresh_chunks(repo, plan, graph.nodes)

            stale_pages = self.store.mark_doc_pages_stale(
                repo_id,
                file_paths=plan.changed_files + plan.deleted_files,
                graph_refs=stale_graph_refs,
            )
            result = IncrementalUpdateResult(
                run_id=run.id,
                repo_id=repo_id,
                status="done",
                plan=plan,
                scanned_count=scan.scanned_count,
                parsed_file_count=len({symbol.file_path for symbol in parsed_symbols}),
                reused_file_count=len(plan.unchanged_files),
                node_count=len(graph.nodes),
                edge_count=len(graph.edges),
                community_count=len(communities.communities),
                chunk_count=chunk_count,
                stale_pages=stale_pages,
                errors=parse_errors,
            )
            self.store.finish_analysis_run(run.id, status="done", stats=result.stats())
            return result
        except Exception as exc:
            self.store.finish_analysis_run(run.id, status="failed", stats={}, error=str(exc))
            raise

    def _repo(self, repo_id: str) -> RepoDescriptor:
        repo = self.store.get_repo(repo_id)
        if repo is None:
            raise ValueError(f"Repository not found: {repo_id}")
        return repo

    def _parse_scan(
        self,
        files: list[ScannedFile],
        *,
        repo_root: Path,
        only_paths: set[str],
    ) -> tuple[list[AstSymbol], list[dict[str, str]]]:
        symbols: list[AstSymbol] = []
        errors: list[dict[str, str]] = []
        for scanned_file in files:
            if scanned_file.path not in only_paths or not scanned_file.is_source:
                continue
            try:
                parsed_symbols = self.parser.parse_file(
                    Path(scanned_file.absolute_path),
                    repo_root=repo_root,
                    language=scanned_file.language,
                )
            except SyntaxError as exc:
                errors.append({"file_path": scanned_file.path, "error": str(exc)})
                continue
            symbols.extend(parsed_symbols)
        return symbols, errors

    def _refresh_chunks(
        self,
        repo: RepoDescriptor,
        plan: IncrementalUpdatePlan,
        nodes: list[CodeGraphNode],
    ) -> int:
        existing_chunks = self.store.list_code_chunks(repo.id)
        if not existing_chunks:
            return 0

        refreshed_file_paths = plan.affected_files
        source_file_paths = set(plan.changed_files + plan.new_files)
        refreshed_nodes = [node for node in nodes if node.file_path in source_file_paths]
        refreshed_chunks = self.graphrag.build_source_chunks(
            repo_id=repo.id,
            repo_path=repo.path,
            nodes=refreshed_nodes,
        )
        self.store.replace_code_chunks_for_files(repo.id, refreshed_file_paths, refreshed_chunks)
        return len(self.store.list_code_chunks(repo.id))


def _plan_from_scan(
    repo_id: str,
    scan: RepoScanResult,
    current_nodes: list[CodeGraphNode],
) -> IncrementalUpdatePlan:
    current_file_hashes = {
        node.file_path: node.hash
        for node in current_nodes
        if node.type == "file" and node.file_path
    }
    scanned_file_hashes = {scanned_file.path: scanned_file.sha256 for scanned_file in scan.files}

    changed_files = sorted(
        path
        for path, file_hash in scanned_file_hashes.items()
        if path in current_file_hashes and current_file_hashes[path] != file_hash
    )
    new_files = sorted(path for path in scanned_file_hashes if path not in current_file_hashes)
    deleted_files = sorted(path for path in current_file_hashes if path not in scanned_file_hashes)
    unchanged_files = sorted(
        path
        for path, file_hash in scanned_file_hashes.items()
        if current_file_hashes.get(path) == file_hash
    )
    return IncrementalUpdatePlan(
        repo_id=repo_id,
        changed_files=changed_files,
        new_files=new_files,
        deleted_files=deleted_files,
        unchanged_files=unchanged_files,
    )


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


def _affected_graph_refs(
    nodes: list[CodeGraphNode],
    edges: list[CodeGraphEdge],
    file_paths: list[str],
) -> list[str]:
    file_path_set = set(file_paths)
    affected_node_ids = {
        node.id
        for node in nodes
        if node.file_path in file_path_set
    }
    affected_edge_ids = {
        edge.id
        for edge in edges
        if edge.source_id in affected_node_ids or edge.target_id in affected_node_ids
    }
    return sorted(affected_node_ids | affected_edge_ids)


def _string_or_none(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item is not None]
