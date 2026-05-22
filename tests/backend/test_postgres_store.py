import os
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from backend.app.database import (
    CodeChunkEmbeddingRecord,
    CodeChunkRecord,
    DocPageRecord,
    create_store,
)
from backend.app.services.analyzer import AnalysisService
from backend.app.services.graph import CodeGraphEdge, CodeGraphNode
from backend.app.services.incremental import IncrementalUpdater
from backend.app.services.repo_scanner import RepoDescriptor, RepoScanner


pytestmark = pytest.mark.skipif(
    not os.getenv("CODEWIKI_TEST_POSTGRES_URL"),
    reason="Set CODEWIKI_TEST_POSTGRES_URL to run PostgreSQL integration tests.",
)


@pytest.fixture
def postgres_store():
    base_url = os.environ["CODEWIKI_TEST_POSTGRES_URL"]
    schema = f"codewiki_test_{uuid.uuid4().hex}"
    admin_engine = create_engine(base_url, future=True)
    with admin_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))

    url = make_url(base_url)
    query = dict(url.query)
    query["options"] = f"-csearch_path={schema}"
    store_url = url.set(query=query).render_as_string(hide_password=False)
    store = create_store(store_url)
    with store.sql_connection() as connection:
        assert connection.execute(text("SELECT current_schema()")).scalar_one() == schema
    try:
        yield store
    finally:
        store.close()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()


def test_postgres_store_persists_core_graph_and_chunk_records(postgres_store) -> None:
    repo = RepoDescriptor(
        id="pg-repo",
        name="pg repo",
        path="/tmp/pg-repo",
        source_type="local",
        git_url=None,
        commit_hash=None,
    )
    postgres_store.upsert_repo(repo)

    nodes = [
        CodeGraphNode(
            id="node-file",
            repo_id=repo.id,
            type="file",
            name="service.py",
            file_path="service.py",
            start_line=1,
            end_line=10,
            language="python",
            symbol_id="service.py",
            summary="service file",
            hash="file-hash",
            metadata={},
        ),
        CodeGraphNode(
            id="node-fn",
            repo_id=repo.id,
            type="function",
            name="handle_request",
            file_path="service.py",
            start_line=2,
            end_line=8,
            language="python",
            symbol_id="service.handle_request",
            summary="handles requests",
            hash="fn-hash",
            metadata={},
        ),
    ]
    edges = [
        CodeGraphEdge(
            id="edge-1",
            repo_id=repo.id,
            source_id="node-file",
            target_id="node-fn",
            type="contains",
            confidence=1.0,
            weight=1.0,
            is_inferred=False,
            metadata={},
        )
    ]
    postgres_store.replace_graph(repo.id, nodes=nodes, edges=edges)

    search_hits = postgres_store.search_code_nodes(repo.id, "handle_request", limit=5)
    assert [hit.node.id for hit in search_hits] == ["node-fn"]
    assert search_hits[0].reasons == ("postgres_fts",)

    chunk = CodeChunkRecord(
        id="chunk-1",
        repo_id=repo.id,
        node_id="node-fn",
        file_path="service.py",
        start_line=2,
        end_line=8,
        content="def handle_request(): return 'ok'",
        content_hash="chunk-hash",
        token_count=6,
    )
    other_chunk = CodeChunkRecord(
        id="chunk-2",
        repo_id=repo.id,
        node_id="node-file",
        file_path="service.py",
        start_line=1,
        end_line=1,
        content="module constants",
        content_hash="other-chunk-hash",
        token_count=2,
    )
    postgres_store.replace_code_chunks(repo.id, [chunk, other_chunk])
    chunk_hits = postgres_store.search_code_chunks_fts(repo.id, "handle_request", limit=5)
    assert [hit.chunk.id for hit in chunk_hits] == ["chunk-1"]
    assert chunk_hits[0].match_type == "postgres_fts"

    embeddings = [
        CodeChunkEmbeddingRecord(
            id="embedding-1",
            repo_id=repo.id,
            chunk_id="chunk-1",
            model="test-embedding",
            dimensions=3,
            embedding=[0.1, 0.2, 0.3],
            content_hash="chunk-hash",
        ),
        CodeChunkEmbeddingRecord(
            id="embedding-2",
            repo_id=repo.id,
            chunk_id="chunk-2",
            model="test-embedding",
            dimensions=3,
            embedding=[0.9, 0.1, 0.1],
            content_hash="other-chunk-hash",
        ),
    ]
    postgres_store.replace_code_chunk_embeddings(
        repo.id,
        model="test-embedding",
        embeddings=embeddings,
    )

    rows = postgres_store.list_code_chunk_embeddings(repo.id, model="test-embedding")
    assert len(rows) == 2
    assert {row.chunk_id: row.embedding for row in rows} == {
        "chunk-1": [0.1, 0.2, 0.3],
        "chunk-2": [0.9, 0.1, 0.1],
    }
    vector_hits = postgres_store.search_code_chunk_embeddings(
        repo.id,
        model="test-embedding",
        query_embedding=[0.1, 0.2, 0.3],
    )
    assert [hit.chunk.id for hit in vector_hits] == ["chunk-1", "chunk-2"]
    assert vector_hits[0].match_type == "pgvector"


def test_postgres_store_covers_analysis_wiki_llm_and_delete(
    postgres_store,
    tmp_path: Path,
) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "main.py").write_text("def main():\n    return 1\n", encoding="utf-8")

    repo = postgres_store.upsert_repo(RepoScanner().describe(str(repo_dir)))
    result = AnalysisService(store=postgres_store).analyze(repo.id)
    nodes, edges = postgres_store.get_graph(repo.id)

    assert result.status == "done"
    assert postgres_store.list_analysis_runs(repo.id)[0].stats["node_count"] == len(nodes)
    assert edges

    catalog = postgres_store.save_doc_catalog(
        repo.id,
        title="Project Wiki",
        structure={"items": [{"slug": "main", "title": "Main"}]},
        language_code="en",
    )
    page = postgres_store.upsert_doc_page(
        DocPageRecord(
            id="page-main",
            repo_id=repo.id,
            language_code="en",
            slug="main",
            title="Main",
            parent_slug=None,
            markdown="# Main\n",
            source_refs=[{"file_path": "main.py"}],
            graph_refs=[nodes[0].id],
            status="generated",
            updated_at=None,
        )
    )
    llm_run = postgres_store.record_llm_run(
        repo.id,
        task_type="qa",
        model="fake/qa",
        input_hash="input-hash",
        cache_key="cache-key",
        response_content="answer",
        response_usage={"prompt_tokens": 1, "completion_tokens": 2},
    )
    chunk = CodeChunkRecord(
        id="delete-check-chunk",
        repo_id=repo.id,
        node_id=nodes[0].id,
        file_path="main.py",
        start_line=1,
        end_line=2,
        content="def main(): return 1",
        content_hash="delete-check-hash",
        token_count=4,
    )
    postgres_store.replace_code_chunks(repo.id, [chunk])
    postgres_store.replace_code_chunk_embeddings(
        repo.id,
        model="test-embedding",
        embeddings=[
            CodeChunkEmbeddingRecord(
                id="embedding-delete-check",
                repo_id=repo.id,
                chunk_id=chunk.id,
                model="test-embedding",
                dimensions=3,
                embedding=[0.1, 0.2, 0.3],
                content_hash=chunk.content_hash,
            )
        ],
    )

    assert postgres_store.get_latest_doc_catalog(repo.id).id == catalog.id
    assert postgres_store.get_doc_page(repo.id, "main").id == page.id
    assert (
        postgres_store.get_cached_llm_run(
            repo.id,
            task_type="qa",
            cache_key="cache-key",
            input_hash="input-hash",
            model="fake/qa",
        ).id
        == llm_run.id
    )

    assert postgres_store.delete_repo(repo.id) is True
    assert postgres_store.get_repo(repo.id) is None
    assert postgres_store.list_analysis_runs(repo.id) == []
    assert postgres_store.list_doc_pages(repo.id) == []
    assert postgres_store.list_llm_runs(repo.id) == []
    assert postgres_store.get_graph(repo.id) == ([], [])
    with postgres_store.sql_connection() as connection:
        assert (
            connection.execute(text("SELECT count(*) FROM code_chunk_embedding_vec_3")).scalar_one()
            == 0
        )


def test_postgres_store_covers_incremental_update(
    postgres_store,
    tmp_path: Path,
) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "service.py").write_text("def answer():\n    return 42\n", encoding="utf-8")
    (repo_dir / "api.py").write_text(
        "from service import answer\n\ndef handler():\n    return answer()\n",
        encoding="utf-8",
    )

    repo = postgres_store.upsert_repo(RepoScanner().describe(str(repo_dir)))
    AnalysisService(store=postgres_store).analyze(repo.id)
    postgres_store.upsert_doc_page(
        DocPageRecord(
            id="page-api",
            repo_id=repo.id,
            language_code="en",
            slug="api",
            title="API",
            parent_slug=None,
            markdown="# API\n",
            source_refs=[{"file_path": "api.py", "start_line": 3, "end_line": 4}],
            graph_refs=[],
            status="generated",
            updated_at=None,
        )
    )

    (repo_dir / "api.py").write_text(
        "from service import answer\n\ndef handler():\n    return answer() + 1\n",
        encoding="utf-8",
    )
    (repo_dir / "util.py").write_text("def helper():\n    return 'ok'\n", encoding="utf-8")

    result = IncrementalUpdater(store=postgres_store).update(repo.id)
    nodes, _edges = postgres_store.get_graph(repo.id)

    assert result.status == "done"
    assert result.plan.changed_files == ["api.py"]
    assert result.plan.new_files == ["util.py"]
    assert result.parsed_file_count == 2
    assert result.stale_pages == ["api"]
    assert postgres_store.get_doc_page(repo.id, "api").status == "draft"
    assert postgres_store.list_analysis_runs(repo.id)[0].stats["mode"] == "incremental"
    assert any(node.file_path == "util.py" and node.name == "helper" for node in nodes)
