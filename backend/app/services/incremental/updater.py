from pathlib import Path

from backend.app.database import SQLiteStore, get_store
from backend.app.services.ast_parser import AstParser, AstSymbol
from backend.app.services.community_detector import CommunityDetector
from backend.app.services.graph_builder import CodeGraphNode, GraphBuilder
from backend.app.services.graph_rag import GraphRAGRetriever
from backend.app.services.incremental.models import IncrementalUpdatePlan, IncrementalUpdateResult
from backend.app.services.incremental.planning import _affected_graph_refs, _plan_from_scan
from backend.app.services.incremental.symbol_recovery import _symbols_from_existing_graph
from backend.app.services.incremental.wiki_regeneration import (
    regenerate_stale_wiki_pages,
    skipped_wiki_regeneration,
)
from backend.app.services.repo_scanner import RepoDescriptor, RepoScanner, ScannedFile


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

    async def update_with_wiki_regeneration(
        self,
        repo_id: str,
        *,
        refresh_chunks: bool = True,
        regenerate_wiki: bool = True,
    ) -> tuple[IncrementalUpdateResult, dict[str, object]]:
        result = self.update(repo_id, refresh_chunks=refresh_chunks)
        wiki_regeneration = (
            await regenerate_stale_wiki_pages(self.store, repo_id, result.stale_pages)
            if regenerate_wiki
            else skipped_wiki_regeneration(result.stale_pages)
        )
        return result, wiki_regeneration

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
