from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from backend.app.config import Settings, get_settings
from backend.app.database import CodeWikiStore
from backend.app.services.analysis_pipeline import AnalysisPipeline
from backend.app.services.ast_parser import AstParser
from backend.app.services.async_tasks import run_blocking
from backend.app.services.community.detector import CommunityDetector
from backend.app.services.community.namer import CommunityNamer
from backend.app.services.community.naming import CommunityNamingResult
from backend.app.services.graph import CodeGraph, CodeGraphNode, GraphBuilder
from backend.app.services.llm_gateway import LLMGateway
from backend.app.services.model_router import ModelRouter
from backend.app.services.repo_metadata import read_repo_metadata, write_repo_metadata
from backend.app.services.repo_scanner import (
    RepoDescriptor,
    RepoScanResult,
    RepoScanner,
    git_diff_changed_paths,
)


@dataclass(frozen=True)
class AnalysisResult:
    run_id: str
    repo_id: str
    status: str
    scanned_count: int
    parsed_file_count: int
    node_count: int
    edge_count: int
    community_count: int
    community_count_by_level: dict[str, int] = field(default_factory=dict)
    errors: list[dict[str, str]] = field(default_factory=list)
    mode: str = "full"
    reused_file_count: int = 0

    def stats(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "scanned_count": self.scanned_count,
            "parsed_file_count": self.parsed_file_count,
            "reused_file_count": self.reused_file_count,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "community_count": self.community_count,
            "community_count_by_level": self.community_count_by_level,
            "errors": self.errors,
        }


@dataclass(frozen=True)
class AnalysisWithCommunitySummariesResult:
    analysis: AnalysisResult
    community_naming: CommunityNamingResult | None = None


class AnalysisService:
    def __init__(
        self,
        *,
        store: CodeWikiStore,
        scanner: RepoScanner | None = None,
        parser: AstParser | None = None,
        graph_builder: GraphBuilder | None = None,
        community_detector: CommunityDetector | None = None,
    ) -> None:
        self.store = store
        self.scanner = scanner or RepoScanner()
        self.parser = parser or AstParser()
        self.graph_builder = graph_builder or GraphBuilder()
        self.community_detector = community_detector or CommunityDetector()
        self.pipeline = AnalysisPipeline(
            store=self.store,
            scanner=self.scanner,
            parser=self.parser,
            graph_builder=self.graph_builder,
            community_detector=self.community_detector,
        )

    async def analyze_with_community_summaries(
        self,
        repo_id: str,
        *,
        name_communities: bool = True,
        force: bool = False,
        community_namer: CommunityNamer | None = None,
        settings: Settings | None = None,
        progress_callback: Callable[[str, dict[str, object]], None] | None = None,
    ) -> AnalysisWithCommunitySummariesResult:
        result = await run_blocking(
            self.analyze,
            repo_id,
            force=force,
            progress_callback=progress_callback,
        )
        if not name_communities:
            return AnalysisWithCommunitySummariesResult(analysis=result)

        settings = settings or get_settings()
        if community_namer is None and not _llm_configured(settings):
            naming_result = CommunityNamingResult(
                repo_id=repo_id,
                status="skipped",
                renamed_count=0,
                community_count=result.community_count,
                errors=["LLM community naming skipped because no LLM endpoint or API key is configured."],
            )
            return AnalysisWithCommunitySummariesResult(
                analysis=result,
                community_naming=naming_result,
            )

        namer = community_namer or CommunityNamer(LLMGateway(settings), store=self.store)
        try:
            naming_result = await _summarize_communities(namer, repo_id)
        except Exception as exc:
            naming_result = CommunityNamingResult(
                repo_id=repo_id,
                status="failed",
                renamed_count=0,
                community_count=result.community_count,
                errors=[str(exc)],
            )
        return AnalysisWithCommunitySummariesResult(
            analysis=result,
            community_naming=naming_result,
        )

    def analyze(
        self,
        repo_id: str,
        *,
        force: bool = False,
        progress_callback: Callable[[str, dict[str, object]], None] | None = None,
    ) -> AnalysisResult:
        repo = self.store.get_repo(repo_id)
        if repo is None:
            raise ValueError(f"Repository not found: {repo_id}")

        run = self.store.create_analysis_run(repo_id)
        try:
            old_nodes, old_edges = self.store.get_graph(repo_id)
            _emit_progress(progress_callback, "scan_start", repo=repo.name, path=repo.path)
            scan = self._scan_repo_for_analysis(repo, old_nodes, force=force)
            _emit_progress(
                progress_callback,
                "scan_done",
                scanned=scan.scanned_count,
                ignored=scan.ignored_count,
                skipped=scan.skipped_count,
            )
            incremental_plan = (
                None if force or not old_nodes else self._incremental_plan(repo, scan, old_nodes)
            )
            if incremental_plan is not None:
                _emit_progress(
                    progress_callback,
                    "plan_done",
                    changed=len(incremental_plan.changed_files),
                    new=len(incremental_plan.new_files),
                    deleted=len(incremental_plan.deleted_files),
                    unchanged=len(incremental_plan.unchanged_files),
                )
            if incremental_plan is not None and not incremental_plan.affected_files:
                existing_communities = self.store.list_graph_communities(repo_id)
                result = AnalysisResult(
                    run_id=run.id,
                    repo_id=repo_id,
                    status="done",
                    scanned_count=scan.scanned_count,
                    parsed_file_count=0,
                    reused_file_count=len(incremental_plan.unchanged_files),
                    node_count=len(old_nodes),
                    edge_count=len(old_edges),
                    community_count=len(existing_communities),
                    community_count_by_level=_community_count_by_level(existing_communities),
                    mode="unchanged",
                )
                self.store.finish_analysis_run(run.id, status="done", stats=result.stats())
                self.store.upsert_repo(scan.repo)
                write_repo_metadata(scan.repo)
                _emit_progress(progress_callback, "analysis_done", mode=result.mode)
                return result

            if incremental_plan is not None:
                from backend.app.services.incremental.symbol_recovery import _symbols_from_existing_graph

                changed_or_new = set(incremental_plan.changed_files + incremental_plan.new_files)
                reused_symbols = _symbols_from_existing_graph(
                    old_nodes,
                    old_edges,
                    set(incremental_plan.unchanged_files),
                )
                pipeline_result = self.pipeline.run(
                    scan,
                    only_paths=changed_or_new,
                    reused_symbols=reused_symbols,
                    progress_callback=progress_callback,
                )
                mode = "incremental"
                reused_file_count = len(incremental_plan.unchanged_files)
            else:
                pipeline_result = self.pipeline.run(scan, progress_callback=progress_callback)
                mode = "full"
                reused_file_count = 0

            result = AnalysisResult(
                run_id=run.id,
                repo_id=repo_id,
                status="done",
                scanned_count=pipeline_result.scan.scanned_count,
                parsed_file_count=pipeline_result.parsed_file_count,
                node_count=len(pipeline_result.graph.nodes),
                edge_count=len(pipeline_result.graph.edges),
                community_count=len(pipeline_result.communities),
                community_count_by_level=_community_count_by_level(pipeline_result.communities),
                errors=pipeline_result.parse_errors,
                mode=mode,
                reused_file_count=reused_file_count,
            )
            self.store.finish_analysis_run(run.id, status="done", stats=result.stats())
            self.store.upsert_repo(pipeline_result.scan.repo)
            write_repo_metadata(pipeline_result.scan.repo)
            _emit_progress(
                progress_callback,
                "analysis_done",
                mode=result.mode,
                nodes=result.node_count,
                edges=result.edge_count,
            )
            return result
        except Exception as exc:
            self.store.finish_analysis_run(
                run.id,
                status="failed",
                stats={},
                error=str(exc),
            )
            raise

    def build_graph_for_path(self, path: str) -> CodeGraph:
        return self.pipeline.build_graph_for_path(path)

    def _scan_repo_for_analysis(
        self,
        repo: RepoDescriptor,
        old_nodes: list[CodeGraphNode],
        *,
        force: bool,
    ) -> RepoScanResult:
        if force or not old_nodes:
            return self.pipeline.scan_repo(repo)
        current_repo = self.scanner.describe(repo.path, name=repo.name, source_type=repo.source_type)
        candidate_paths = self._git_diff_candidates(repo, current_repo.commit_hash)
        return self.pipeline.scan_repo(
            current_repo,
            known_hashes=_known_hashes_from_nodes(old_nodes),
            known_file_metadata=_known_file_metadata_from_nodes(old_nodes),
            hash_paths=candidate_paths,
        )

    def _incremental_plan(
        self,
        repo: RepoDescriptor,
        scan: RepoScanResult,
        old_nodes: list[CodeGraphNode],
    ) -> Any:
        from backend.app.services.incremental.planning import _plan_from_scan

        base_commit, head_commit, candidate_paths = self._git_diff_context(repo, scan.repo.commit_hash)
        detection_strategy = "git_diff+sha256" if candidate_paths is not None else "sha256"
        return _plan_from_scan(
            repo.id,
            scan,
            old_nodes,
            candidate_paths=candidate_paths,
            detection_strategy=detection_strategy,
            base_commit=base_commit,
            head_commit=head_commit,
        )

    def _git_diff_candidates(self, repo: RepoDescriptor, head_commit: str | None) -> set[str] | None:
        _base_commit, _head_commit, candidate_paths = self._git_diff_context(repo, head_commit)
        return candidate_paths

    def _git_diff_context(
        self,
        repo: RepoDescriptor,
        head_commit: str | None,
    ) -> tuple[str | None, str | None, set[str] | None]:
        metadata = read_repo_metadata(repo.id)
        base_commit = metadata.commit_hash if metadata is not None else repo.commit_hash
        return (
            base_commit,
            head_commit,
            git_diff_changed_paths(Path(repo.path), base_commit, head_commit),
        )


def _llm_configured(settings: Settings) -> bool:
    profile = ModelRouter(settings).profile_for("community_summary")
    return bool(
        profile.api_key
        or profile.endpoint
        or profile.provider_type
        or not profile.model.startswith("provider/")
    )


def _emit_progress(
    progress_callback: Callable[[str, dict[str, object]], None] | None,
    stage: str,
    **payload: object,
) -> None:
    if progress_callback is not None:
        progress_callback(stage, payload)


async def _summarize_communities(namer: CommunityNamer, repo_id: str) -> CommunityNamingResult:
    summarize = getattr(namer, "summarize_communities", None)
    if callable(summarize):
        return await summarize(repo_id)
    return await namer.name_communities(repo_id)


def _community_count_by_level(communities) -> dict[str, int]:
    counts: dict[str, int] = {}
    for community in communities:
        level = str(int(getattr(community, "level", 0) or 0))
        counts[level] = counts.get(level, 0) + 1
    return counts


def _known_hashes_from_nodes(nodes: list[CodeGraphNode]) -> dict[str, str]:
    return {
        node.file_path: node.hash
        for node in nodes
        if node.type == "file" and node.file_path and node.hash
    }


def _known_file_metadata_from_nodes(nodes: list[CodeGraphNode]) -> dict[str, tuple[int | None, str | None]]:
    metadata: dict[str, tuple[int | None, str | None]] = {}
    for node in nodes:
        if node.type != "file" or not node.file_path:
            continue
        size = node.metadata.get("size_bytes")
        modified_at = node.metadata.get("modified_at")
        metadata[node.file_path] = (
            size if isinstance(size, int) else None,
            modified_at if isinstance(modified_at, str) else None,
        )
    return metadata
