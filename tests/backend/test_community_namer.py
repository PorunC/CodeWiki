import json
from pathlib import Path

import pytest

from backend.app.database import SQLiteStore
from backend.app.services.analyzer import AnalysisService
from backend.app.services.community_namer import CommunityNamer
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
