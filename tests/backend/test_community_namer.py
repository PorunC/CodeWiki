import json
from pathlib import Path

import pytest

from backend.app.database import GraphCommunityRecord, SQLiteStore
from backend.app.services.analyzer import AnalysisService
from backend.app.services.community.edges import CommunityEdgeBuilder
from backend.app.services.community.namer import CommunityNamer, _select_naming_targets
from backend.app.services.community.naming import apply_llm_names, fallback_name_from_payload, naming_payload
from backend.app.services.graph import CodeGraphEdge, CodeGraphNode
from backend.app.services.llm_gateway import LLMResult
from backend.app.services.repo_scanner import RepoScanner


@pytest.mark.asyncio
async def test_community_namer_updates_names_from_llm_without_changing_membership(
    tmp_path: Path,
) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "graph_rag.py").write_text(
        "def retrieve_context():\n"
        "    return 'context'\n"
    )
    (repo_dir / "wiki_generator.py").write_text(
        "from graph_rag import retrieve_context\n\n"
        "def generate_page():\n"
        "    return retrieve_context()\n"
    )

    store = SQLiteStore(tmp_path / "codewiki.sqlite3")
    repo = store.upsert_repo(RepoScanner().describe(str(repo_dir)))
    AnalysisService(store=store).analyze(repo.id)
    before = store.list_graph_communities(repo.id)
    assert before

    target_id = before[0].id
    result = await CommunityNamer(_FakeCommunityLLM(target_id), store=store).name_communities(repo.id)
    after = store.list_graph_communities(repo.id)

    assert result.status == "renamed"
    assert result.renamed_count >= 1
    renamed = next(community for community in after if community.id == target_id)
    assert renamed.name == "Wiki Retrieval Pipeline"
    assert "GraphRAG retrieval to wiki page generation" in (renamed.summary or "")
    assert renamed.node_ids == before[0].node_ids
    assert store.list_llm_runs(repo.id, task_type="community_summary")


@pytest.mark.asyncio
async def test_community_namer_rejects_generic_llm_names(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "community_detector.py").write_text("def detect():\n    return []\n")

    store = SQLiteStore(tmp_path / "codewiki.sqlite3")
    repo = store.upsert_repo(RepoScanner().describe(str(repo_dir)))
    AnalysisService(store=store).analyze(repo.id)
    before = store.list_graph_communities(repo.id)
    target_id = before[0].id

    await CommunityNamer(_FakeGenericCommunityLLM(target_id), store=store).name_communities(repo.id)
    renamed = next(community for community in store.list_graph_communities(repo.id) if community.id == target_id)

    assert renamed.name != "backend subsystem"
    assert "Community Detector" in renamed.name


@pytest.mark.asyncio
async def test_community_namer_rebuilds_community_edges_after_renaming(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    store = SQLiteStore(tmp_path / "codewiki.sqlite3")
    repo = store.upsert_repo(RepoScanner().describe(str(repo_dir)))
    nodes = [
        CodeGraphNode(id="node-a", repo_id=repo.id, type="function", name="alpha", file_path="a.py"),
        CodeGraphNode(id="node-b", repo_id=repo.id, type="function", name="beta", file_path="b.py"),
    ]
    edges = [
        CodeGraphEdge(id="edge-a-b", repo_id=repo.id, source_id="node-a", target_id="node-b", type="calls")
    ]
    communities = [
        _community("parent", repo_id=repo.id, level=0, node_ids=["node-a", "node-b"]),
        _community("child-a", repo_id=repo.id, level=1, parent_id="parent", node_ids=["node-a"]),
        _community("child-b", repo_id=repo.id, level=1, parent_id="parent", node_ids=["node-b"]),
    ]
    store.replace_graph(repo.id, nodes=nodes, edges=edges)
    store.replace_graph_communities(repo.id, communities)
    store.replace_graph_community_edges(repo.id, CommunityEdgeBuilder().build(repo.id, communities, edges))
    assert {edge.type for edge in store.list_graph_community_edges(repo.id)} == {"calls_into", "contains"}

    await CommunityNamer(_FakeCommunityLLM("parent"), store=store).name_communities(repo.id)

    assert {edge.type for edge in store.list_graph_community_edges(repo.id)} == {"calls_into", "contains"}


def test_community_namer_rejects_cluster_number_names() -> None:
    community = GraphCommunityRecord(
        id="community-1",
        repo_id="repo-1",
        name="Cluster 23",
        level=0,
        node_ids=["node-1"],
        summary="Cluster 23 was detected by graspologic_leiden.",
        summary_hash=None,
        created_at=None,
    )
    content = json.dumps(
        {
            "communities": [
                {
                    "id": community.id,
                    "name": "Cluster 23",
                    "summary": "Contains package initialization code.",
                }
            ]
        }
    )

    renamed, errors = apply_llm_names(
        [community],
        [community],
        content,
        fallback_names={community.id: "Api Package"},
    )

    assert errors == []
    assert renamed[0].name == "Api Package"


def test_fallback_name_uses_init_package_and_dotfile_evidence() -> None:
    assert fallback_name_from_payload({"files": ["backend/app/api/__init__.py"]}) == "Api Package"
    assert fallback_name_from_payload({"files": [".gitignore"]}) == "Gitignore"


def test_community_namer_selects_targets_across_hierarchy() -> None:
    parent = _community("parent", level=0, rank=0, node_ids=["parent:a"])
    child = _community("child", level=1, parent_id="parent", node_ids=["child:a", "child:b"])
    detail = _community("detail", level=2, parent_id="child", node_ids=["detail:a", "detail:b", "detail:c"])

    selected = _select_naming_targets([parent, child, detail], max_communities=3)

    assert [community.id for community in selected] == ["parent", "child", "detail"]


def test_naming_payload_includes_parent_context() -> None:
    parent = _community("parent", name="GraphRAG Pipeline", level=0)
    child = _community("child", name="Context Packing", level=1, parent_id="parent")

    payload = naming_payload(
        "repo",
        "Repo",
        "/repo",
        [child],
        {},
        [],
        all_communities=[parent, child],
    )

    community = payload["communities"][0]
    assert community["parent_name"] == "GraphRAG Pipeline"
    assert community["ancestor_names"] == ["GraphRAG Pipeline"]


class _FakeCommunityLLM:
    def __init__(self, community_id: str) -> None:
        self.community_id = community_id

    async def complete(
        self,
        task_type: str,
        messages: list[dict[str, str]],
        *,
        response_format: str | None = None,
    ) -> LLMResult:
        assert task_type == "community_summary"
        assert response_format == "json_object"
        assert "Name and summarize graph communities" in messages[0]["content"]
        assert "Return only JSON in the requested shape" in messages[0]["content"]
        payload_text = "\n".join(message["content"] for message in messages)
        assert self.community_id in payload_text
        payload = {
            "communities": [
                {
                    "id": self.community_id,
                    "name": "Wiki Retrieval Pipeline",
                    "summary": "GraphRAG retrieval to wiki page generation with source-grounded context.",
                }
            ]
        }
        return LLMResult(content=json.dumps(payload), model="fake/community", usage={})


class _FakeGenericCommunityLLM:
    def __init__(self, community_id: str) -> None:
        self.community_id = community_id

    async def complete(
        self,
        task_type: str,
        messages: list[dict[str, str]],
        *,
        response_format: str | None = None,
    ) -> LLMResult:
        payload = {
            "communities": [
                {
                    "id": self.community_id,
                    "name": "backend subsystem",
                    "summary": "Detects communities in the code graph.",
                }
            ]
        }
        return LLMResult(content=json.dumps(payload), model="fake/community", usage={})


def _community(
    community_id: str,
    *,
    repo_id: str = "repo",
    name: str | None = None,
    level: int = 0,
    parent_id: str | None = None,
    rank: int = 0,
    node_ids: list[str] | None = None,
) -> GraphCommunityRecord:
    return GraphCommunityRecord(
        id=community_id,
        repo_id=repo_id,
        name=name or community_id.title(),
        level=level,
        parent_id=parent_id,
        rank=rank,
        node_ids=node_ids or [f"{community_id}:node"],
        summary=f"{community_id} summary",
        summary_hash=None,
        created_at=None,
    )
