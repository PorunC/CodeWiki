import networkx as nx

from backend.app.services.community_detector import CommunityDetector, _partition
from backend.app.services.graph import CodeGraphEdge, CodeGraphNode


def test_partition_prefers_graspologic_leiden_when_available() -> None:
    graph = nx.Graph()
    graph.add_edge("api.py", "service.py", weight=1.0)
    graph.add_edge("service.py", "models.py", weight=0.8)
    graph.add_edge("ui.tsx", "hooks.ts", weight=1.0)
    graph.add_edge("api.py", "ui.tsx", weight=0.05)

    communities, algorithm = _partition(graph)

    assert algorithm == "graspologic_leiden"
    assert set().union(*communities) == set(graph.nodes)


def test_detector_returns_partitions_without_names_or_summaries() -> None:
    nodes = [
        CodeGraphNode(id="repo:file:a.py", repo_id="repo", type="file", name="a.py", file_path="a.py"),
        CodeGraphNode(id="repo:file:b.py", repo_id="repo", type="file", name="b.py", file_path="b.py"),
    ]
    edges = [
        CodeGraphEdge(
            id="edge-1",
            repo_id="repo",
            source_id="repo:file:a.py",
            target_id="repo:file:b.py",
            type="imports",
        )
    ]

    result = CommunityDetector().detect(nodes, edges)

    assert result.algorithm
    assert result.partitions == [["repo:file:a.py", "repo:file:b.py"]]
    assert not hasattr(result, "communities")
