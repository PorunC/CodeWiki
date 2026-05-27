from backend.app.database import GraphCommunityRecord
from backend.app.services.community.edges import CommunityEdgeBuilder
from backend.app.services.graph import CodeGraphEdge


def test_community_edge_builder_generates_contains_and_dependency_edges() -> None:
    parent = GraphCommunityRecord(
        id="repo:community:0:parent",
        repo_id="repo",
        name="Parent",
        level=0,
        parent_id=None,
        rank=0,
        node_ids=["node-a", "node-b"],
        summary=None,
        summary_hash=None,
        created_at=None,
    )
    child_a = GraphCommunityRecord(
        id="repo:community:1:a",
        repo_id="repo",
        name="A",
        level=1,
        parent_id=parent.id,
        rank=0,
        node_ids=["node-a"],
        summary=None,
        summary_hash=None,
        created_at=None,
    )
    child_b = GraphCommunityRecord(
        id="repo:community:1:b",
        repo_id="repo",
        name="B",
        level=1,
        parent_id=parent.id,
        rank=1,
        node_ids=["node-b"],
        summary=None,
        summary_hash=None,
        created_at=None,
    )
    code_edges = [
        CodeGraphEdge(
            id="edge-1",
            repo_id="repo",
            source_id="node-a",
            target_id="node-b",
            type="calls",
            confidence=0.8,
            weight=2.0,
        ),
        CodeGraphEdge(
            id="edge-2",
            repo_id="repo",
            source_id="node-a",
            target_id="node-b",
            type="imports",
            confidence=1.0,
            weight=1.0,
        ),
    ]

    edges = CommunityEdgeBuilder().build("repo", [parent, child_a, child_b], code_edges)

    assert {(edge.source_community_id, edge.target_community_id, edge.type) for edge in edges} == {
        (parent.id, child_a.id, "contains"),
        (parent.id, child_b.id, "contains"),
        (child_a.id, child_b.id, "calls_into"),
        (child_a.id, child_b.id, "imports_from"),
    }
    calls_edge = next(edge for edge in edges if edge.type == "calls_into")
    assert calls_edge.weight == 2.0
    assert calls_edge.confidence == 0.8
    assert calls_edge.evidence_edge_ids == ["edge-1"]
