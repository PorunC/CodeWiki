from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.app.config import get_settings
from backend.app.database import SQLiteStore
from backend.app.db.store import get_store
from backend.app.main import create_app
from backend.app.services.analyzer import AnalysisService
from backend.app.services.graph_rag import GraphRAGRetriever
from backend.app.services.repo_scanner import RepoScanner


@pytest.mark.asyncio
async def test_graphrag_retrieve_lazily_builds_chunks_and_returns_context(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "service.py").write_text(
        "\n".join(
            [
                "class Service:",
                "    def run(self):",
                "        return 'ok'",
                "",
                "def build_service():",
                "    return Service()",
            ]
        )
        + "\n"
    )
    (repo_dir / "api.py").write_text(
        "\n".join(
            [
                "from service import Service",
                "",
                "def handler():",
                "    service = Service()",
                "    return service.run()",
            ]
        )
        + "\n"
    )

    store = SQLiteStore(tmp_path / "codewiki.sqlite3")
    repo = store.upsert_repo(RepoScanner().describe(str(repo_dir)))
    AnalysisService(store=store).analyze(repo.id)
    assert store.list_code_chunks(repo.id) == []

    trace = await GraphRAGRetriever(store=store).retrieve(repo.id, "handler Service run", max_hops=2)

    assert store.list_code_chunks(repo.id)
    assert any(node["name"] == "handler" for node in trace.seed_nodes)
    assert trace.expanded_nodes
    assert any("def handler" in chunk["content"] for chunk in trace.source_chunks)
    assert trace.related_edges
    assert trace.context_pack["chunk_count"] == len(trace.source_chunks)
    assert "Graph Facts:" in trace.context_pack["text"]


@pytest.mark.asyncio
async def test_graphrag_builds_optional_litellm_embedding_index(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "main.py").write_text("def answer():\n    return 42\n")

    store = SQLiteStore(tmp_path / "codewiki.sqlite3")
    repo = store.upsert_repo(RepoScanner().describe(str(repo_dir)))
    AnalysisService(store=store).analyze(repo.id)

    retriever = GraphRAGRetriever(store=store, llm=_FakeLLM())
    result = await retriever.build_index(repo.id, include_embeddings=True)
    trace = await retriever.retrieve(repo.id, "unmatched semantic query", include_embeddings=True)

    assert result.embedding_count == result.chunk_count
    assert store.list_code_chunk_embeddings(repo.id, model="fake/embed")
    assert any("vector" in chunk["reasons"] for chunk in trace.source_chunks)


def test_graphrag_retrieve_http_returns_real_context(tmp_path: Path, monkeypatch) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "main.py").write_text(
        "\n".join(
            [
                "def answer():",
                "    return 42",
                "",
                "def handler():",
                "    return answer()",
            ]
        )
        + "\n"
    )
    monkeypatch.setenv(
        "CODEWIKI_DATABASE_URL",
        f"sqlite+aiosqlite:///{tmp_path / 'api-codewiki.sqlite3'}",
    )
    get_settings.cache_clear()
    get_store.cache_clear()

    client = TestClient(create_app())
    repo_response = client.post("/api/repos", json={"path": str(repo_dir), "name": "repo"})
    repo_response.raise_for_status()
    repo_id = repo_response.json()["id"]
    analyze_response = client.post(f"/api/repos/{repo_id}/analyze")
    analyze_response.raise_for_status()

    response = client.post(
        f"/api/repos/{repo_id}/graphrag/retrieve",
        json={"query": "handler answer", "max_hops": 2},
    )
    response.raise_for_status()
    data = response.json()

    assert data["seed_nodes"]
    assert data["source_chunks"]
    assert data["related_edges"]
    assert "def handler" in data["context_pack"]["text"]

    get_settings.cache_clear()
    get_store.cache_clear()


class _FakeRouter:
    def profile_for(self, task_type: str) -> SimpleNamespace:
        assert task_type == "embedding"
        return SimpleNamespace(model="fake/embed")


class _FakeLLM:
    router = _FakeRouter()

    async def embed(self, texts: list[str], *, task_type: str = "embedding") -> list[list[float]]:
        assert task_type == "embedding"
        return [[float(len(text) % 7 + 1), 1.0] for text in texts]
