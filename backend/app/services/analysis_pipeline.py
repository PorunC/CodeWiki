from dataclasses import dataclass
from pathlib import Path
from collections.abc import Callable, Mapping

from backend.app.database import GraphCommunityEdgeRecord, GraphCommunityRecord, CodeWikiStore
from backend.app.services.ast_parser import AstParser, AstSymbol, parse_scanned_files
from backend.app.services.community.detector import CommunityDetector
from backend.app.services.community.edges import CommunityEdgeBuilder
from backend.app.services.community.records import CommunityRecordBuilder
from backend.app.services.graph import CodeGraph, GraphBuilder
from backend.app.services.repo_scanner import RepoDescriptor, RepoScanResult, RepoScanner
from backend.app.services.source_file_cache import SourceFileContentProvider


@dataclass(frozen=True)
class AnalysisPipelineResult:
    scan: RepoScanResult
    graph: CodeGraph
    communities: list[GraphCommunityRecord]
    community_edges: list[GraphCommunityEdgeRecord]
    community_algorithm: str
    parsed_symbols: list[AstSymbol]
    parse_errors: list[dict[str, str]]

    @property
    def parsed_file_count(self) -> int:
        return len({symbol.file_path for symbol in self.parsed_symbols})


class AnalysisPipeline:
    def __init__(
        self,
        *,
        store: CodeWikiStore,
        scanner: RepoScanner | None = None,
        parser: AstParser | None = None,
        graph_builder: GraphBuilder | None = None,
        community_detector: CommunityDetector | None = None,
        community_record_builder: CommunityRecordBuilder | None = None,
        community_edge_builder: CommunityEdgeBuilder | None = None,
    ) -> None:
        self.store = store
        self.scanner = scanner or RepoScanner()
        self.parser = parser or AstParser()
        self.graph_builder = graph_builder or GraphBuilder()
        self.community_detector = community_detector or CommunityDetector()
        self.community_record_builder = community_record_builder or CommunityRecordBuilder()
        self.community_edge_builder = community_edge_builder or CommunityEdgeBuilder()

    def scan_repo(
        self,
        repo: RepoDescriptor,
        *,
        known_hashes: Mapping[str, str] | None = None,
        known_file_metadata: Mapping[str, tuple[int | None, str | None]] | None = None,
        hash_paths: set[str] | None = None,
    ) -> RepoScanResult:
        return self.scanner.scan(
            repo.path,
            name=repo.name,
            source_type=repo.source_type,
            known_hashes=known_hashes,
            known_file_metadata=known_file_metadata,
            hash_paths=hash_paths,
        )

    def build_graph_for_path(self, path: str) -> CodeGraph:
        scan = self.scanner.scan(path)
        symbols, _errors = parse_scanned_files(
            self.parser,
            scan.files,
            repo_root=Path(scan.repo.path),
            content_provider=SourceFileContentProvider(scan.repo.path),
        )
        return self.graph_builder.build(scan, symbols)

    def run(
        self,
        scan: RepoScanResult,
        *,
        only_paths: set[str] | None = None,
        reused_symbols: list[AstSymbol] | None = None,
        persist: bool = True,
        progress_callback: Callable[[str, dict[str, object]], None] | None = None,
    ) -> AnalysisPipelineResult:
        parse_total = sum(
            1
            for scanned_file in scan.files
            if scanned_file.is_source and (only_paths is None or scanned_file.path in only_paths)
        )
        _emit_progress(
            progress_callback,
            "parse_start",
            total=parse_total,
            reused_files=len(reused_symbols or []),
        )
        parsed_symbols, parse_errors = parse_scanned_files(
            self.parser,
            scan.files,
            repo_root=Path(scan.repo.path),
            only_paths=only_paths,
            content_provider=SourceFileContentProvider(scan.repo.path),
            progress_callback=lambda completed, total, path: _emit_progress(
                progress_callback,
                "parse_progress",
                completed=completed,
                total=total,
                path=path,
            ),
        )
        _emit_progress(
            progress_callback,
            "parse_done",
            parsed_files=len({symbol.file_path for symbol in parsed_symbols}),
            symbols=len(parsed_symbols),
            errors=len(parse_errors),
        )
        _emit_progress(progress_callback, "graph_start", symbols=len(parsed_symbols) + len(reused_symbols or []))
        graph = self.graph_builder.build(scan, [*(reused_symbols or []), *parsed_symbols])
        _emit_progress(progress_callback, "graph_done", nodes=len(graph.nodes), edges=len(graph.edges))
        _emit_progress(progress_callback, "communities_start", nodes=len(graph.nodes), edges=len(graph.edges))
        community_partitions = self.community_detector.detect(graph.nodes, graph.edges)
        communities = self.community_record_builder.build_all(
            scan.repo.id,
            community_partitions.communities,
            graph.nodes,
            graph.edges,
            community_partitions.algorithm,
        )
        community_edges = self.community_edge_builder.build(scan.repo.id, communities, graph.edges)
        _emit_progress(
            progress_callback,
            "communities_done",
            communities=len(communities),
            community_edges=len(community_edges),
        )

        if persist:
            _emit_progress(
                progress_callback,
                "persist_start",
                nodes=len(graph.nodes),
                edges=len(graph.edges),
                communities=len(communities),
            )
            self.store.replace_graph(scan.repo.id, nodes=graph.nodes, edges=graph.edges)
            self.store.replace_graph_communities(scan.repo.id, communities)
            self.store.replace_graph_community_edges(scan.repo.id, community_edges)
            _emit_progress(progress_callback, "persist_done")

        return AnalysisPipelineResult(
            scan=scan,
            graph=graph,
            communities=communities,
            community_edges=community_edges,
            community_algorithm=community_partitions.algorithm,
            parsed_symbols=parsed_symbols,
            parse_errors=parse_errors,
        )


def _emit_progress(
    progress_callback: Callable[[str, dict[str, object]], None] | None,
    stage: str,
    **payload: object,
) -> None:
    if progress_callback is not None:
        progress_callback(stage, payload)
