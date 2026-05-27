import networkx as nx

import backend.app.services.community.detector as community_detector
from backend.app.services.community.detector import CommunityDetector, _partition
from backend.app.services.graph import CodeGraphEdge, CodeGraphNode


def test_partition_prefers_networkx_louvain_for_default_speed() -> None:
    graph = nx.Graph()
    graph.add_edge("api.py", "service.py", weight=1.0)
    graph.add_edge("service.py", "models.py", weight=0.8)
    graph.add_edge("ui.tsx", "hooks.ts", weight=1.0)
    graph.add_edge("api.py", "ui.tsx", weight=0.05)

    communities, algorithm = _partition(graph)

    assert algorithm == "networkx_louvain"
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
    assert len(result.communities) == 1
    assert result.communities[0].level == 0
    assert result.communities[0].parent_key is None


def test_detector_builds_parent_child_hierarchy(monkeypatch) -> None:
    nodes = [
        CodeGraphNode(id=f"repo:file:{name}.py", repo_id="repo", type="file", name=f"{name}.py", file_path=f"{name}.py")
        for name in ("api", "service", "db", "model")
    ]
    edges = [
        CodeGraphEdge(id="e1", repo_id="repo", source_id=nodes[0].id, target_id=nodes[1].id, type="imports"),
        CodeGraphEdge(id="e2", repo_id="repo", source_id=nodes[2].id, target_id=nodes[3].id, type="imports"),
        CodeGraphEdge(id="e3", repo_id="repo", source_id=nodes[1].id, target_id=nodes[2].id, type="calls"),
    ]

    def fake_partition(graph, *, resolution=1.0):
        if all(isinstance(node, int) for node in graph.nodes):
            return [{0, 1}, {2, 3}], "fake_parent"
        return [
            {nodes[0].id},
            {nodes[1].id},
            {nodes[2].id},
            {nodes[3].id},
        ], "fake_leaf"

    monkeypatch.setattr(community_detector, "_partition", fake_partition)
    monkeypatch.setattr(community_detector, "MIN_CHILD_NODES", 1)
    monkeypatch.setattr(community_detector, "MIN_PARENT_NODES", 1)

    result = CommunityDetector().detect(nodes, edges)

    parents = [community for community in result.communities if community.level == 0]
    children = [community for community in result.communities if community.level == 1]
    assert len(parents) == 2
    assert len(children) == 4
    assert {child.parent_key for child in children} == {parent.key for parent in parents}


def test_detector_splits_large_children_into_detail_communities(monkeypatch) -> None:
    nodes = [
        CodeGraphNode(
            id=f"repo:file:{index}.py",
            repo_id="repo",
            type="file",
            name=f"{index}.py",
            file_path=f"{index}.py",
        )
        for index in range(6)
    ]
    edges = [
        CodeGraphEdge(
            id=f"edge-{index}",
            repo_id="repo",
            source_id=nodes[index].id,
            target_id=nodes[index + 1].id,
            type="imports",
        )
        for index in range(5)
    ]

    def fake_partition(graph, *, resolution=1.0):
        graph_nodes = list(graph.nodes)
        if all(isinstance(node, int) for node in graph_nodes):
            return [{0, 1}], "fake_parent"
        if resolution == community_detector.DETAIL_RESOLUTION:
            ordered = sorted(str(node) for node in graph_nodes)
            split_at = max(1, len(ordered) // 2)
            return [set(ordered[:split_at]), set(ordered[split_at:])], "fake_detail"
        return [set(node.id for node in nodes[:3]), set(node.id for node in nodes[3:])], "fake_leaf"

    monkeypatch.setattr(community_detector, "_partition", fake_partition)
    monkeypatch.setattr(community_detector, "MIN_CHILD_NODES", 1)
    monkeypatch.setattr(community_detector, "MIN_PARENT_NODES", 1)
    monkeypatch.setattr(community_detector, "DETAIL_SPLIT_NODE_THRESHOLD", 1)
    monkeypatch.setattr(community_detector, "MIN_DETAIL_NODES", 1)

    result = CommunityDetector().detect(nodes, edges)

    children = [community for community in result.communities if community.level == 1]
    details = [community for community in result.communities if community.level == 2]
    assert children
    assert len(details) == 4
    assert {detail.parent_key for detail in details} <= {child.key for child in children}
