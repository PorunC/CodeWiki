from pathlib import Path

from backend.app.database import CodeWikiStore
from backend.app.services.analysis_pipeline import AnalysisPipeline
from backend.app.services.ast_parser import AstParser
from backend.app.services.async_tasks import run_blocking
from backend.app.services.community_detector import CommunityDetector
from backend.app.services.analyzer import (
    _community_count_by_level,
    _known_file_metadata_from_nodes,
    _known_hashes_from_nodes,
)
from backend.app.services.graph import CodeGraphNode, GraphBuilder
from backend.app.services.graphrag import GraphRAGRetriever
from backend.app.services.incremental.models import IncrementalUpdatePlan, IncrementalUpdateResult
from backend.app.services.incremental.planning import _affected_graph_refs, _plan_from_scan
from backend.app.services.incremental.symbol_recovery import _symbols_from_existing_graph
from backend.app.services.incremental.wiki_regeneration import (
    regenerate_stale_wiki_pages,
    skipped_wiki_regeneration,
)
from backend.app.services.repo_metadata import read_repo_metadata, write_repo_metadata
from backend.app.services.repo_scanner import (
    RepoDescriptor,
    RepoScanResult,
    RepoScanner,
    git_diff_changed_paths,
)


class IncrementalUpdater:
    def __init__(
        self,
        *,
        store: CodeWikiStore,
        scanner: RepoScanner | None = None,
        parser: AstParser | None = None,
        graph_builder: GraphBuilder | None = None,
        community_detector: CommunityDetector | None = None,
        graphrag: GraphRAGRetriever | None = None,
    ) -> None:
        self.store = store
        self.scanner = scanner or RepoScanner()
        self.parser = parser or AstParser()
        self.graph_builder = graph_builder or GraphBuilder()
        self.community_detector = community_detector or CommunityDetector()
        self.graphrag = graphrag or GraphRAGRetriever(store=self.store)
        self.pipeline = AnalysisPipeline(
            store=self.store,
            scanner=self.scanner,
            parser=self.parser,
            graph_builder=self.graph_builder,
            community_detector=self.community_detector,
        )

    def plan(self, repo_id: str) -> IncrementalUpdatePlan:
        repo = self._repo(repo_id)
        nodes, _edges = self.store.get_graph(repo_id)
        scan = self._scan_repo_for_update(repo, nodes)
        return self._plan_from_scan_with_metadata(repo, scan, nodes)

    def update(self, repo_id: str, *, refresh_chunks: bool = True) -> IncrementalUpdateResult:
        repo = self._repo(repo_id)
        old_nodes, old_edges = self.store.get_graph(repo_id)
        scan = self._scan_repo_for_update(repo, old_nodes)
        plan = self._plan_from_scan_with_metadata(repo, scan, old_nodes)
        stale_graph_refs = _affected_graph_refs(old_nodes, old_edges, plan.changed_files + plan.deleted_files)
        run = self.store.create_analysis_run(repo_id)

        try:
            if not plan.affected_files:
                chunk_count = len(self.store.list_code_chunks(repo_id))
                existing_communities = self.store.list_graph_communities(repo_id)
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
                    community_count=len(existing_communities),
                    chunk_count=chunk_count,
                    community_count_by_level=_community_count_by_level(existing_communities),
                )
                self.store.finish_analysis_run(run.id, status="done", stats=result.stats())
                self.store.upsert_repo(scan.repo)
                write_repo_metadata(scan.repo)
                return result

            changed_or_new = set(plan.changed_files + plan.new_files)
            reused_symbols = _symbols_from_existing_graph(old_nodes, old_edges, set(plan.unchanged_files))
            pipeline_result = self.pipeline.run(
                scan,
                only_paths=changed_or_new,
                reused_symbols=reused_symbols,
            )

            chunk_count = len(self.store.list_code_chunks(repo_id))
            if refresh_chunks:
                chunk_count = self._refresh_chunks(repo, plan, pipeline_result.graph.nodes)

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
                parsed_file_count=pipeline_result.parsed_file_count,
                reused_file_count=len(plan.unchanged_files),
                node_count=len(pipeline_result.graph.nodes),
                edge_count=len(pipeline_result.graph.edges),
                community_count=len(pipeline_result.communities),
                chunk_count=chunk_count,
                community_count_by_level=_community_count_by_level(pipeline_result.communities),
                stale_pages=stale_pages,
                errors=pipeline_result.parse_errors,
            )
            self.store.finish_analysis_run(run.id, status="done", stats=result.stats())
            self.store.upsert_repo(scan.repo)
            write_repo_metadata(scan.repo)
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
        result = await run_blocking(self.update, repo_id, refresh_chunks=refresh_chunks)
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

    def _scan_repo_for_update(
        self,
        repo: RepoDescriptor,
        old_nodes: list[CodeGraphNode],
    ) -> RepoScanResult:
        if not old_nodes:
            return self.pipeline.scan_repo(repo)
        current_repo = self.scanner.describe(repo.path, name=repo.name, source_type=repo.source_type)
        candidate_paths = self._git_diff_candidate_paths(repo, current_repo.commit_hash)
        return self.pipeline.scan_repo(
            current_repo,
            known_hashes=_known_hashes_from_nodes(old_nodes),
            known_file_metadata=_known_file_metadata_from_nodes(old_nodes),
            hash_paths=candidate_paths,
        )

    def _plan_from_scan_with_metadata(
        self,
        repo: RepoDescriptor,
        scan: RepoScanResult,
        nodes: list[CodeGraphNode],
    ) -> IncrementalUpdatePlan:
        candidate_paths, detection_strategy, base_commit, head_commit = self._git_diff_candidates(
            repo,
            scan,
        )
        return _plan_from_scan(
            repo.id,
            scan,
            nodes,
            candidate_paths=candidate_paths,
            detection_strategy=detection_strategy,
            base_commit=base_commit,
            head_commit=head_commit,
        )

    def _git_diff_candidates(
        self,
        repo: RepoDescriptor,
        scan: RepoScanResult,
    ) -> tuple[set[str] | None, str, str | None, str | None]:
        metadata = read_repo_metadata(repo.id)
        base_commit = metadata.commit_hash if metadata is not None else repo.commit_hash
        head_commit = scan.repo.commit_hash
        diff_paths = self._git_diff_candidate_paths(repo, head_commit)
        if diff_paths is None:
            return None, "sha256", base_commit, head_commit
        return diff_paths, "git_diff+sha256", base_commit, head_commit

    def _git_diff_candidate_paths(
        self,
        repo: RepoDescriptor,
        head_commit: str | None,
    ) -> set[str] | None:
        metadata = read_repo_metadata(repo.id)
        base_commit = metadata.commit_hash if metadata is not None else repo.commit_hash
        return git_diff_changed_paths(Path(repo.path), base_commit, head_commit)

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
