from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.app.config import Settings, get_settings
from backend.app.database import SQLiteStore
from backend.app.services.ast_parser import AstParser, AstSymbol
from backend.app.services.community_detector import CommunityDetector
from backend.app.services.community_namer import CommunityNamer
from backend.app.services.community_naming import CommunityNamingResult
from backend.app.services.graph_builder import CodeGraph, GraphBuilder
from backend.app.services.llm_gateway import LLMGateway
from backend.app.services.repo_scanner import RepoScanner


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
    errors: list[dict[str, str]] = field(default_factory=list)

    def stats(self) -> dict[str, Any]:
        return {
            "scanned_count": self.scanned_count,
            "parsed_file_count": self.parsed_file_count,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "community_count": self.community_count,
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

    async def analyze_with_community_summaries(
        self,
        repo_id: str,
        *,
        name_communities: bool = True,
        community_namer: CommunityNamer | None = None,
        settings: Settings | None = None,
    ) -> AnalysisWithCommunitySummariesResult:
        result = self.analyze(repo_id)
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
            naming_result = await namer.name_communities(repo_id)
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

    def analyze(self, repo_id: str) -> AnalysisResult:
        repo = self.store.get_repo(repo_id)
        if repo is None:
            raise ValueError(f"Repository not found: {repo_id}")

        run = self.store.create_analysis_run(repo_id)
        try:
            scan = self.scanner.scan(repo.path, name=repo.name, source_type=repo.source_type)
            symbols, parse_errors = self._parse_scan(scan.files, repo_root=Path(scan.repo.path))
            graph = self.graph_builder.build(scan, symbols)
            self.store.replace_graph(repo_id, nodes=graph.nodes, edges=graph.edges)
            communities = self.community_detector.detect(repo_id, graph.nodes, graph.edges)
            self.store.replace_graph_communities(repo_id, communities.communities)

            result = AnalysisResult(
                run_id=run.id,
                repo_id=repo_id,
                status="done",
                scanned_count=scan.scanned_count,
                parsed_file_count=len({symbol.file_path for symbol in symbols}),
                node_count=len(graph.nodes),
                edge_count=len(graph.edges),
                community_count=len(communities.communities),
                errors=parse_errors,
            )
            self.store.finish_analysis_run(run.id, status="done", stats=result.stats())
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
        scan = self.scanner.scan(path)
        symbols, _ = self._parse_scan(scan.files, repo_root=Path(scan.repo.path))
        return self.graph_builder.build(scan, symbols)

    def _parse_scan(self, files, *, repo_root: Path) -> tuple[list[AstSymbol], list[dict[str, str]]]:
        symbols: list[AstSymbol] = []
        errors: list[dict[str, str]] = []

        for scanned_file in files:
            if not scanned_file.is_source:
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
            if parsed_symbols:
                symbols.extend(parsed_symbols)
        return symbols, errors


def _llm_configured(settings: Settings) -> bool:
    return bool(
        settings.llm_api_key
        or settings.llm_base_url
        or (settings.llm_mode == "proxy" and settings.litellm_proxy_base_url)
        or not settings.llm_default_model.startswith("provider/")
    )
