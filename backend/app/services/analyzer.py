from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.app.config import Settings, get_settings
from backend.app.database import SQLiteStore
from backend.app.services.analysis_pipeline import AnalysisPipeline
from backend.app.services.ast_parser import AstParser
from backend.app.services.async_tasks import run_blocking
from backend.app.services.community_detector import CommunityDetector
from backend.app.services.community_namer import CommunityNamer
from backend.app.services.community_naming import CommunityNamingResult
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
        store: SQLiteStore,
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
    ) -> AnalysisWithCommunitySummariesResult:
        result = await run_blocking(self.analyze, repo_id, force=force)
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

    def analyze(self, repo_id: str, *, force: bool = False) -> AnalysisResult:
        repo = self.store.get_repo(repo_id)
        if repo is None:
            raise ValueError(f"Repository not found: {repo_id}")

        run = self.store.create_analysis_run(repo_id)
        try:
            scan = self.pipeline.scan_repo(repo)
            old_nodes, old_edges = self.store.get_graph(repo_id)
            incremental_plan = (
                None if force or not old_nodes else self._incremental_plan(repo, scan, old_nodes)
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
                )
                mode = "incremental"
                reused_file_count = len(incremental_plan.unchanged_files)
            else:
                pipeline_result = self.pipeline.run(scan)
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

    def _incremental_plan(
        self,
        repo: RepoDescriptor,
        scan: RepoScanResult,
        old_nodes: list[CodeGraphNode],
    ) -> Any:
        from backend.app.services.incremental.planning import _plan_from_scan

        metadata = read_repo_metadata(repo.id)
        base_commit = metadata.commit_hash if metadata is not None else repo.commit_hash
        head_commit = scan.repo.commit_hash
        candidate_paths = git_diff_changed_paths(Path(scan.repo.path), base_commit, head_commit)
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


def _llm_configured(settings: Settings) -> bool:
    profile = ModelRouter(settings).profile_for("community_summary")
    return bool(
        profile.api_key
        or profile.endpoint
        or profile.provider_type
        or not profile.model.startswith("provider/")
    )


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
