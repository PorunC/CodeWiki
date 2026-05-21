from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.app.config import get_settings
from backend.app.database import CodeChunkRecord, CodeChunkSearchHit, SQLiteStore
from backend.app.db.store import get_store
from backend.app.main import create_app
from backend.app.services.analyzer import AnalysisService
from backend.app.services.chunk_builder import ChunkBuilder
from backend.app.services.embedding_index import EmbeddingIndex
from backend.app.services.graph import CodeGraphEdge, CodeGraphNode
from backend.app.services.graphrag import GraphRAGRetriever
from backend.app.services.graphrag.ranking import rank_source_chunks
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
    assert trace.community_summaries
    assert "Community Summaries:" in trace.context_pack["text"]
    assert trace.context_pack["chunk_count"] == len(trace.source_chunks)
    assert trace.context_pack["community_count"] == len(trace.community_summaries)
    assert "Graph Facts:" in trace.context_pack["text"]
    assert all(
        {
            "semantic_score",
            "keyword_score",
            "graph_proximity_score",
            "node_importance_score",
            "source_freshness_score",
        }
        <= set(chunk["score_components"])
        for chunk in trace.source_chunks
    )


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


@pytest.mark.asyncio
async def test_chunk_builder_and_embedding_index_are_standalone_services(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "main.py").write_text("def answer():\n    return 42\n")
    store = SQLiteStore(tmp_path / "codewiki.sqlite3")
    repo = store.upsert_repo(RepoScanner().describe(str(repo_dir)))
    node = CodeGraphNode(
        id=f"{repo.id}:function:answer",
        repo_id=repo.id,
        type="function",
        name="answer",
        file_path="main.py",
        start_line=1,
        end_line=2,
    )

    chunks = ChunkBuilder().build_source_chunks(
        repo_id=repo.id,
        repo_path=str(repo_dir),
        nodes=[node],
    )
    store.replace_graph(repo.id, nodes=[node], edges=[])
    store.replace_code_chunks(repo.id, chunks)
    result = await EmbeddingIndex(store, _FakeLLM()).build(repo.id, chunks)

    assert len(chunks) == 1
    assert chunks[0].content == "def answer():\n    return 42\n"
    assert result.count == 1
    assert result.model == "fake/embed"
    assert store.list_code_chunk_embeddings(repo.id, model="fake/embed")[0].chunk_id == chunks[0].id


def test_chunk_builder_skips_file_nodes(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "main.py").write_text("def answer():\n    return 42\n")
    store = SQLiteStore(tmp_path / "codewiki.sqlite3")
    repo = store.upsert_repo(RepoScanner().describe(str(repo_dir)))
    file_node = CodeGraphNode(
        id=f"{repo.id}:file:main.py",
        repo_id=repo.id,
        type="file",
        name="main.py",
        file_path="main.py",
        start_line=1,
        end_line=2,
    )
    function_node = CodeGraphNode(
        id=f"{repo.id}:function:answer",
        repo_id=repo.id,
        type="function",
        name="answer",
        file_path="main.py",
        start_line=1,
        end_line=2,
    )

    chunks = ChunkBuilder().build_source_chunks(
        repo_id=repo.id,
        repo_path=str(repo_dir),
        nodes=[file_node, function_node],
    )

    assert len(chunks) == 1
    assert chunks[0].node_id == function_node.id
    assert chunks[0].content == "def answer():\n    return 42\n"


@pytest.mark.asyncio
async def test_embedding_index_deduplicates_llm_calls_by_content_hash(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    store = SQLiteStore(tmp_path / "codewiki.sqlite3")
    repo = store.upsert_repo(RepoScanner().describe(str(repo_dir)))
    chunks = [
        CodeChunkRecord(
            id="chunk-a",
            repo_id=repo.id,
            node_id=None,
            file_path="a.py",
            start_line=1,
            end_line=1,
            content="return 42\n",
            content_hash="same-content",
            token_count=2,
        ),
        CodeChunkRecord(
            id="chunk-b",
            repo_id=repo.id,
            node_id=None,
            file_path="b.py",
            start_line=1,
            end_line=1,
            content="return 42\n",
            content_hash="same-content",
            token_count=2,
        ),
        CodeChunkRecord(
            id="chunk-c",
            repo_id=repo.id,
            node_id=None,
            file_path="c.py",
            start_line=1,
            end_line=1,
            content="return 43\n",
            content_hash="other-content",
            token_count=2,
        ),
    ]
    store.replace_code_chunks(repo.id, chunks)
    llm = _RecordingLLM()

    result = await EmbeddingIndex(store, llm, batch_size=10).build(repo.id, chunks)

    assert result.count == len(chunks)
    assert sum(len(call) for call in llm.calls) == 2
    assert llm.calls[0][0].startswith("a.py:")
    assert llm.calls[0][1].startswith("c.py:")
    embeddings = {
        embedding.chunk_id: embedding
        for embedding in store.list_code_chunk_embeddings(repo.id, model="fake/embed")
    }
    assert set(embeddings) == {"chunk-a", "chunk-b", "chunk-c"}
    assert embeddings["chunk-a"].embedding == embeddings["chunk-b"].embedding
    assert embeddings["chunk-a"].content_hash == embeddings["chunk-b"].content_hash


@pytest.mark.asyncio
async def test_embedding_index_reuses_existing_vectors_by_content_hash(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    store = SQLiteStore(tmp_path / "codewiki.sqlite3")
    repo = store.upsert_repo(RepoScanner().describe(str(repo_dir)))
    chunks = [
        CodeChunkRecord(
            id="chunk-a",
            repo_id=repo.id,
            node_id=None,
            file_path="a.py",
            start_line=1,
            end_line=1,
            content="return 42\n",
            content_hash="same-content",
            token_count=2,
        )
    ]
    store.replace_code_chunks(repo.id, chunks)
    first_llm = _RecordingLLM()
    second_llm = _RecordingLLM()

    await EmbeddingIndex(store, first_llm).build(repo.id, chunks)
    first_row = store.list_code_chunk_embeddings(repo.id, model="fake/embed")[0]
    result = await EmbeddingIndex(store, second_llm).build(repo.id, chunks)
    second_row = store.list_code_chunk_embeddings(repo.id, model="fake/embed")[0]

    assert result.count == 1
    assert sum(len(call) for call in first_llm.calls) == 1
    assert second_llm.calls == []
    assert second_row.embedding
    assert second_row.vec_rowid == first_row.vec_rowid


@pytest.mark.asyncio
async def test_embedding_index_ensure_builds_missing_chunk_vectors(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    store = SQLiteStore(tmp_path / "codewiki.sqlite3")
    repo = store.upsert_repo(RepoScanner().describe(str(repo_dir)))
    first_chunks = [
        CodeChunkRecord(
            id="chunk-a",
            repo_id=repo.id,
            node_id=None,
            file_path="a.py",
            start_line=1,
            end_line=1,
            content="return 42\n",
            content_hash="same-content",
            token_count=2,
        )
    ]
    second_chunks = [
        *first_chunks,
        CodeChunkRecord(
            id="chunk-b",
            repo_id=repo.id,
            node_id=None,
            file_path="b.py",
            start_line=1,
            end_line=1,
            content="return 43\n",
            content_hash="other-content",
            token_count=2,
        ),
    ]
    store.replace_code_chunks(repo.id, first_chunks)
    llm = _RecordingLLM()

    await EmbeddingIndex(store, llm).build(repo.id, first_chunks)
    store.sync_code_chunks(repo.id, second_chunks)
    result = await EmbeddingIndex(store, llm).ensure(repo.id, second_chunks)

    assert result is not None
    assert result.count == 2
    assert [len(call) for call in llm.calls] == [1, 1]
    embeddings = store.list_code_chunk_embeddings(repo.id, model="fake/embed")
    assert {embedding.chunk_id for embedding in embeddings} == {"chunk-a", "chunk-b"}


def test_graphrag_hybrid_ranking_uses_five_factor_formula() -> None:
    old_chunk = _chunk("old", "node-old", "old.py")
    fresh_chunk = _chunk("fresh", "node-fresh", "fresh.py")
    nodes = [
        CodeGraphNode(
            id="node-old",
            repo_id="repo",
            type="function",
            name="old",
            file_path="old.py",
            metadata={"last_commit_at": "2024-01-01T00:00:00+00:00"},
        ),
        CodeGraphNode(
            id="node-fresh",
            repo_id="repo",
            type="function",
            name="fresh",
            file_path="fresh.py",
            metadata={"last_commit_at": "2024-01-11T00:00:00+00:00"},
        ),
        CodeGraphNode(id="node-helper", repo_id="repo", type="function", name="helper"),
    ]
    edges = [
        CodeGraphEdge(id="edge-1", repo_id="repo", source_id="node-old", target_id="node-fresh", type="calls"),
        CodeGraphEdge(id="edge-2", repo_id="repo", source_id="node-fresh", target_id="node-helper", type="calls"),
    ]

    ranked = rank_source_chunks(
        [old_chunk, fresh_chunk],
        nodes=nodes,
        edges=edges,
        seed_ids={"node-old"},
        hops={"node-old": 0, "node-fresh": 1},
        fts_hits=[CodeChunkSearchHit(chunk=old_chunk, score=0.8, match_type="fts")],
        vector_hits=[CodeChunkSearchHit(chunk=fresh_chunk, score=0.6, match_type="vector")],
    )

    assert [hit.chunk.id for hit in ranked] == ["fresh", "old"]
    assert ranked[0].score == pytest.approx(0.51)
    assert ranked[0].score_components == {
        "semantic_score": 0.6,
        "keyword_score": 0.0,
        "graph_proximity_score": 0.5,
        "node_importance_score": 1.0,
        "source_freshness_score": 1.0,
    }
    assert ranked[1].score == pytest.approx(0.45)


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
    assert data["community_summaries"]
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


class _RecordingLLM:
    router = _FakeRouter()

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def embed(self, texts: list[str], *, task_type: str = "embedding") -> list[list[float]]:
        assert task_type == "embedding"
        self.calls.append(list(texts))
        start = sum(len(call) for call in self.calls[:-1])
        return [[float(start + index + 1), 1.0] for index, _text in enumerate(texts)]


def _chunk(chunk_id: str, node_id: str, file_path: str) -> CodeChunkRecord:
    return CodeChunkRecord(
        id=chunk_id,
        repo_id="repo",
        node_id=node_id,
        file_path=file_path,
        start_line=1,
        end_line=1,
        content=f"{chunk_id}\n",
        content_hash=chunk_id,
        token_count=1,
    )
