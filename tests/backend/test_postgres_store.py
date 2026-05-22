import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from backend.app.database import CodeChunkEmbeddingRecord, CodeChunkRecord, create_store
from backend.app.services.graph import CodeGraphEdge, CodeGraphNode
from backend.app.services.repo_scanner import RepoDescriptor


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
    store = create_store(str(url.set(query=query)))
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
    postgres_store.replace_code_chunks(repo.id, [chunk])
    chunk_hits = postgres_store.search_code_chunks_fts(repo.id, "handle_request", limit=5)
    assert [hit.chunk.id for hit in chunk_hits] == ["chunk-1"]
    assert chunk_hits[0].match_type == "like"

    embedding = CodeChunkEmbeddingRecord(
        id="embedding-1",
        repo_id=repo.id,
        chunk_id="chunk-1",
        model="test-embedding",
        dimensions=3,
        embedding=[0.1, 0.2, 0.3],
        content_hash="chunk-hash",
    )
    postgres_store.replace_code_chunk_embeddings(
        repo.id,
        model="test-embedding",
        embeddings=[embedding],
    )

    rows = postgres_store.list_code_chunk_embeddings(repo.id, model="test-embedding")
    assert len(rows) == 1
    assert rows[0].embedding == []
    assert postgres_store.search_code_chunk_embeddings(
        repo.id,
        model="test-embedding",
        query_embedding=[0.1, 0.2, 0.3],
    ) == []
