from dataclasses import dataclass
from pathlib import Path

from backend.app.database import SQLiteStore
from backend.app.services.ast_parser import AstParser, AstSymbol, parse_scanned_files
from backend.app.services.community_detector import CommunityDetectionResult, CommunityDetector
from backend.app.services.graph import CodeGraph, GraphBuilder
from backend.app.services.repo_scanner import RepoDescriptor, RepoScanResult, RepoScanner


@dataclass(frozen=True)
class AnalysisPipelineResult:
    scan: RepoScanResult
    graph: CodeGraph
    communities: CommunityDetectionResult
    parsed_symbols: list[AstSymbol]
    parse_errors: list[dict[str, str]]

    @property
    def parsed_file_count(self) -> int:
        return len({symbol.file_path for symbol in self.parsed_symbols})


class AnalysisPipeline:
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

    def scan_repo(self, repo: RepoDescriptor) -> RepoScanResult:
        return self.scanner.scan(repo.path, name=repo.name, source_type=repo.source_type)

    def build_graph_for_path(self, path: str) -> CodeGraph:
        scan = self.scanner.scan(path)
        symbols, _errors = parse_scanned_files(
            self.parser,
            scan.files,
            repo_root=Path(scan.repo.path),
        )
        return self.graph_builder.build(scan, symbols)

    def run(
        self,
        scan: RepoScanResult,
        *,
        only_paths: set[str] | None = None,
        reused_symbols: list[AstSymbol] | None = None,
        persist: bool = True,
    ) -> AnalysisPipelineResult:
        parsed_symbols, parse_errors = parse_scanned_files(
            self.parser,
            scan.files,
            repo_root=Path(scan.repo.path),
            only_paths=only_paths,
        )
        graph = self.graph_builder.build(scan, [*(reused_symbols or []), *parsed_symbols])
        communities = self.community_detector.detect(scan.repo.id, graph.nodes, graph.edges)

        if persist:
            self.store.replace_graph(scan.repo.id, nodes=graph.nodes, edges=graph.edges)
            self.store.replace_graph_communities(scan.repo.id, communities.communities)

        return AnalysisPipelineResult(
            scan=scan,
            graph=graph,
            communities=communities,
            parsed_symbols=parsed_symbols,
            parse_errors=parse_errors,
        )

