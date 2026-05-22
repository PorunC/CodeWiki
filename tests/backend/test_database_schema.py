import sqlite3
from pathlib import Path

from backend.app.database import (
    CodeChunkEmbeddingRecord,
    CodeChunkRecord,
    DocPageRecord,
    GraphCommunityEdgeRecord,
    GraphCommunityRecord,
    SQLiteStore,
)
from backend.app.models import Base, CodeNodeRecord, DocCatalogRecord, RepoRecord
from backend.app.services.analyzer import AnalysisService
from backend.app.services.graph import CodeGraphNode
from backend.app.services.repo_scanner.models import RepoDescriptor
from backend.app.services.repo_scanner import RepoScanner


def test_persistence_models_are_sqlalchemy_orm_tables() -> None:
    assert RepoRecord.__table__.name == "repo"
    assert CodeNodeRecord.__table__.name == "code_node"
    assert DocCatalogRecord.__table__.name == "doc_catalog"
    assert {"repo", "code_node", "doc_catalog"} <= set(Base.metadata.tables)


def test_schema_contains_graphrag_wiki_and_llm_tables(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "codewiki.sqlite3")

    with store.connect() as connection:
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

    assert {
        "code_chunk",
        "code_chunk_embedding",
        "code_chunk_fts",
        "code_node_fts",
        "graph_community",
        "doc_catalog",
        "doc_page",
        "llm_run",
    } <= tables
    with store.connect() as connection:
        embedding_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(code_chunk_embedding)").fetchall()
        }
        llm_run_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(llm_run)").fetchall()
        }
        catalog_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(doc_catalog)").fetchall()
        }
        page_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(doc_page)").fetchall()
        }
    assert "embedding_json" not in embedding_columns
    assert {"vec_table", "vec_rowid"} <= embedding_columns
    assert {"response_content", "response_usage_json"} <= llm_run_columns
    assert "language_code" in catalog_columns
    assert "language_code" in page_columns


def test_schema_migrates_existing_repo_git_metadata_columns(tmp_path: Path) -> None:
    database_path = tmp_path / "codewiki.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE repo (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              path TEXT NOT NULL,
              source_type TEXT NOT NULL DEFAULT 'local',
              created_at TEXT DEFAULT CURRENT_TIMESTAMP,
              updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

    store = SQLiteStore(database_path)

    with store.connect() as connection:
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(repo)").fetchall()
        }

    assert {"git_url", "commit_hash"} <= columns


def test_schema_migrates_existing_llm_run_cache_columns(tmp_path: Path) -> None:
    database_path = tmp_path / "codewiki.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE llm_run (
              id TEXT PRIMARY KEY,
              repo_id TEXT NOT NULL,
              task_type TEXT NOT NULL,
              provider TEXT,
              model TEXT NOT NULL,
              model_alias TEXT,
              prompt_version TEXT,
              input_hash TEXT NOT NULL,
              cache_key TEXT NOT NULL,
              tokens_in INTEGER NOT NULL DEFAULT 0,
              tokens_out INTEGER NOT NULL DEFAULT 0,
              cost_usd REAL,
              duration_ms INTEGER,
              cached INTEGER NOT NULL DEFAULT 0,
              status TEXT NOT NULL DEFAULT 'success',
              error TEXT,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

    store = SQLiteStore(database_path)

    with store.connect() as connection:
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(llm_run)").fetchall()
        }

    assert {"response_content", "response_usage_json"} <= columns


def test_replace_graph_deletes_stale_nodes_in_batches(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "codewiki.sqlite3")
    repo = store.upsert_repo(
        RepoDescriptor(id="large-repo", name="large", path=str(tmp_path), source_type="local")
    )
    initial_nodes = [
        CodeGraphNode(
            id=f"{repo.id}:symbol:{index}",
            repo_id=repo.id,
            type="function",
            name=f"symbol_{index}",
        )
        for index in range(1200)
    ]
    kept_nodes = initial_nodes[:10]

    store.replace_graph(repo.id, nodes=initial_nodes, edges=[])
    store.replace_graph(repo.id, nodes=kept_nodes, edges=[])

    nodes, edges = store.get_graph(repo.id)
    assert [node.id for node in nodes] == [node.id for node in kept_nodes]
    assert edges == []


def test_schema_rebuilds_missing_code_node_fts_rows(tmp_path: Path) -> None:
    database_path = tmp_path / "codewiki.sqlite3"
    store = SQLiteStore(database_path)
    repo = store.upsert_repo(
        RepoDescriptor(id="fts-repo", name="fts", path=str(tmp_path), source_type="local")
    )
    node = CodeGraphNode(
        id=f"{repo.id}:symbol:main",
        repo_id=repo.id,
        type="function",
        name="main",
    )
    store.replace_graph(repo.id, nodes=[node], edges=[])
    with store.connect() as connection:
        connection.execute("DELETE FROM code_node_fts WHERE id = ?", (node.id,))

    SQLiteStore(database_path)

    with store.connect() as connection:
        fts_count = connection.execute("SELECT COUNT(*) FROM code_node_fts").fetchone()[0]
    assert fts_count == 1


def test_schema_keeps_existing_code_node_fts_rows_without_duplicates(tmp_path: Path) -> None:
    database_path = tmp_path / "codewiki.sqlite3"
    store = SQLiteStore(database_path)
    repo = store.upsert_repo(
        RepoDescriptor(id="fts-repo", name="fts", path=str(tmp_path), source_type="local")
    )
    nodes = [
        CodeGraphNode(
            id=f"{repo.id}:symbol:{index}",
            repo_id=repo.id,
            type="function",
            name=f"symbol_{index}",
        )
        for index in range(3)
    ]
    store.replace_graph(repo.id, nodes=nodes, edges=[])

    SQLiteStore(database_path)

    with store.connect() as connection:
        fts_count = connection.execute("SELECT COUNT(*) FROM code_node_fts").fetchone()[0]
        unique_fts_count = connection.execute(
            "SELECT COUNT(DISTINCT id) FROM code_node_fts"
        ).fetchone()[0]
    assert fts_count == len(nodes)
    assert unique_fts_count == len(nodes)


def test_graphrag_wiki_and_llm_records_round_trip(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "main.py").write_text("def main():\n    return 1\n")

    store = SQLiteStore(tmp_path / "codewiki.sqlite3")
    repo = store.upsert_repo(RepoScanner().describe(str(repo_dir)))
    AnalysisService(store=store).analyze(repo.id)
    nodes, _edges = store.get_graph(repo.id)
    file_node = next(node for node in nodes if node.type == "file")

    chunk = CodeChunkRecord(
        id="chunk-1",
        repo_id=repo.id,
        node_id=file_node.id,
        file_path="main.py",
        start_line=1,
        end_line=2,
        content="def main():\n    return 1\n",
        content_hash="hash-main",
        token_count=7,
    )
    store.replace_code_chunks(repo.id, [chunk])
    assert store.list_code_chunks(repo.id) == [chunk]
    fts_hits = store.search_code_chunks_fts(repo.id, '"main"', limit=5)
    assert fts_hits[0].chunk.id == chunk.id

    embedding = CodeChunkEmbeddingRecord(
        id="embedding-1",
        repo_id=repo.id,
        chunk_id=chunk.id,
        model="fake/embed",
        dimensions=2,
        embedding=[1.0, 0.0],
        content_hash=chunk.content_hash,
        created_at=None,
    )
    store.replace_code_chunk_embeddings(repo.id, model="fake/embed", embeddings=[embedding])
    embeddings = store.list_code_chunk_embeddings(repo.id, model="fake/embed")
    assert embeddings[0].embedding == [1.0, 0.0]
    with store.connect() as connection:
        vec_table_exists = connection.execute(
            """
            SELECT 1 FROM sqlite_master
            WHERE name = 'code_chunk_embedding_vec_2'
            """
        ).fetchone()
    assert vec_table_exists is not None
    vector_hits = store.search_code_chunk_embeddings(
        repo.id,
        model="fake/embed",
        query_embedding=[1.0, 0.1],
        limit=5,
    )
    assert vector_hits[0].chunk.id == chunk.id

    replacement_chunk = CodeChunkRecord(
        id="chunk-2",
        repo_id=repo.id,
        node_id=file_node.id,
        file_path="other.py",
        start_line=1,
        end_line=1,
        content="print('other')\n",
        content_hash="hash-other",
        token_count=3,
    )
    store.sync_code_chunks(repo.id, [chunk, replacement_chunk])
    chunks = store.list_code_chunks(repo.id)
    assert [item.id for item in chunks] == ["chunk-1", "chunk-2"]
    assert store.search_code_chunks_fts(repo.id, '"other"', limit=5)[0].chunk.id == "chunk-2"

    store.sync_code_chunks(repo.id, [replacement_chunk])
    chunks = store.list_code_chunks(repo.id)
    assert [item.id for item in chunks] == ["chunk-2"]
    assert store.search_code_chunks_fts(repo.id, '"main"', limit=5) == []

    community = GraphCommunityRecord(
        id="community-1",
        repo_id=repo.id,
        name="Core",
        level=0,
        node_ids=[file_node.id],
        summary="Core files",
        summary_hash="summary-hash",
        created_at=None,
    )
    store.replace_graph_communities(repo.id, [community])
    communities = store.list_graph_communities(repo.id)
    assert len(communities) == 1
    assert communities[0].node_ids == [file_node.id]
    assert communities[0].summary == "Core files"

    child = GraphCommunityRecord(
        id="community-2",
        repo_id=repo.id,
        name="Core Child",
        level=1,
        parent_id=community.id,
        rank=0,
        node_ids=[file_node.id],
        summary="Core child files",
        summary_hash="summary-hash-child",
        created_at=None,
    )
    store.replace_graph_communities(repo.id, [community, child])
    community_edge = GraphCommunityEdgeRecord(
        id="community-edge-1",
        repo_id=repo.id,
        source_community_id=community.id,
        target_community_id=child.id,
        type="contains",
        weight=1.0,
        confidence=1.0,
        reason="Parent contains child.",
        evidence_edge_ids=[],
        created_at=None,
    )
    store.replace_graph_community_edges(repo.id, [community_edge])
    community_edges = store.list_graph_community_edges(repo.id)
    assert len(community_edges) == 1
    assert community_edges[0].type == "contains"
    assert community_edges[0].source_community_id == community.id
    assert community_edges[0].target_community_id == child.id

    catalog = store.save_doc_catalog(
        repo.id,
        title="Code Wiki",
        structure={"items": [{"title": "Overview", "slug": "overview"}]},
    )
    latest_catalog = store.get_latest_doc_catalog(repo.id)
    assert latest_catalog is not None
    assert latest_catalog.id == catalog.id
    assert latest_catalog.language_code == "en"
    assert latest_catalog.structure["items"][0]["slug"] == "overview"

    page = DocPageRecord(
        id="page-1",
        repo_id=repo.id,
        slug="overview",
        title="Overview",
        parent_slug=None,
        markdown="# Overview",
        source_refs=[{"file_path": "main.py", "start_line": 1, "end_line": 2}],
        graph_refs=[file_node.id],
        status="generated",
        updated_at=None,
    )
    saved_page = store.upsert_doc_page(page)
    assert saved_page.updated_at is not None
    loaded_page = store.get_doc_page(repo.id, "overview")
    assert loaded_page is not None
    assert loaded_page.language_code == "en"
    assert loaded_page.source_refs[0]["file_path"] == "main.py"
    assert store.list_doc_pages(repo.id)[0].slug == "overview"

    llm_run = store.record_llm_run(
        repo.id,
        task_type="page",
        provider="openai",
        model="openai/example",
        model_alias="page_writer",
        prompt_version="page:v1",
        input_hash="input-hash",
        cache_key="cache-key",
        tokens_in=10,
        tokens_out=20,
        cost_usd=0.001,
        duration_ms=123,
        response_content="generated content",
        response_usage={"prompt_tokens": 10, "completion_tokens": 20},
        cached=False,
    )
    runs = store.list_llm_runs(repo.id, task_type="page")
    assert runs == [llm_run]
    assert runs[0].tokens_in == 10
    assert runs[0].cost_usd == 0.001
    assert runs[0].response_content == "generated content"
    assert runs[0].response_usage["completion_tokens"] == 20
    cached_run = store.get_cached_llm_run(
        repo.id,
        task_type="page",
        cache_key="cache-key",
        input_hash="input-hash",
        model="openai/example",
        prompt_version="page:v1",
    )
    assert cached_run == llm_run

    assert store.delete_repo(repo.id) is True
    assert store.delete_repo(repo.id) is False
    assert store.get_repo(repo.id) is None
    assert store.list_code_chunks(repo.id) == []
    assert store.list_code_chunk_embeddings(repo.id, model="fake/embed") == []
    assert store.list_graph_communities(repo.id) == []
    assert store.list_doc_pages(repo.id) == []
    assert store.list_llm_runs(repo.id, task_type="page") == []
    with store.connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) AS count FROM code_chunk_fts WHERE repo_id = ?",
            (repo.id,),
        ).fetchone()["count"] == 0
        assert connection.execute(
            "SELECT COUNT(*) AS count FROM code_chunk_embedding_vec_2 WHERE repo_id = ?",
            (repo.id,),
        ).fetchone()["count"] == 0
