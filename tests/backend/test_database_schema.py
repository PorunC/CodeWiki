from pathlib import Path

from backend.app.database import (
    CodeChunkRecord,
    DocPageRecord,
    GraphCommunityRecord,
    SQLiteStore,
)
from backend.app.services.analyzer import AnalysisService
from backend.app.services.repo_scanner import RepoScanner


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
        "graph_community",
        "doc_catalog",
        "doc_page",
        "llm_run",
    } <= tables


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
    store.upsert_graph_community(community)
    communities = store.list_graph_communities(repo.id)
    assert len(communities) == 1
    assert communities[0].node_ids == [file_node.id]
    assert communities[0].summary == "Core files"

    catalog = store.save_doc_catalog(
        repo.id,
        title="Code Wiki",
        structure={"items": [{"title": "Overview", "slug": "overview"}]},
    )
    latest_catalog = store.get_latest_doc_catalog(repo.id)
    assert latest_catalog is not None
    assert latest_catalog.id == catalog.id
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
        cached=False,
    )
    runs = store.list_llm_runs(repo.id, task_type="page")
    assert runs == [llm_run]
    assert runs[0].tokens_in == 10
    assert runs[0].cost_usd == 0.001
