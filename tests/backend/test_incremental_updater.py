from pathlib import Path

import pytest

from backend.app.database import DocPageRecord, SQLiteStore
from backend.app.services.analyzer import AnalysisService
from backend.app.services.graph_rag import GraphRAGRetriever
from backend.app.services.incremental_updater import IncrementalUpdater
from backend.app.services.repo_scanner import RepoScanner


@pytest.mark.asyncio
async def test_incremental_update_reuses_unchanged_files_refreshes_chunks_and_marks_docs(
    tmp_path: Path,
) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "service.py").write_bytes(b"def answer():\n    return 42\n")
    (repo_dir / "api.py").write_bytes(
        b"from service import answer\n\n"
        b"def handler():\n"
        b"    return answer()\n"
    )

    store = SQLiteStore(tmp_path / "codewiki.sqlite3")
    repo = store.upsert_repo(RepoScanner().describe(str(repo_dir)))
    AnalysisService(store=store).analyze(repo.id)
    await GraphRAGRetriever(store=store).build_index(repo.id)
    store.upsert_doc_page(
        DocPageRecord(
            id="page-api",
            repo_id=repo.id,
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

    (repo_dir / "api.py").write_bytes(
        b"from service import answer\n\n"
        b"def handler():\n"
        b"    return answer() + 1\n"
    )
    (repo_dir / "util.py").write_bytes(b"def helper():\n    return 'ok'\n")

    result = IncrementalUpdater(store=store).update(repo.id)
    nodes, _edges = store.get_graph(repo.id)
    chunks = store.list_code_chunks(repo.id)

    assert result.plan.changed_files == ["api.py"]
    assert result.plan.new_files == ["util.py"]
    assert "service.py" in result.plan.unchanged_files
    assert result.parsed_file_count == 2
    assert result.reused_file_count == 1
    assert any(node.file_path == "service.py" and node.name == "answer" for node in nodes)
    assert any(node.file_path == "util.py" and node.name == "helper" for node in nodes)
    assert any(chunk.file_path == "api.py" and "answer() + 1" in chunk.content for chunk in chunks)
    assert any(chunk.file_path == "util.py" and "def helper" in chunk.content for chunk in chunks)
    assert all(chunk.node_id for chunk in chunks if chunk.file_path == "service.py")
    assert store.get_doc_page(repo.id, "api").status == "draft"
    assert result.stale_pages == ["api"]
    assert store.list_analysis_runs(repo.id)[0].stats["mode"] == "incremental"


def test_incremental_update_removes_deleted_files_and_chunks(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    service_path = repo_dir / "service.py"
    service_path.write_bytes(b"def answer():\n    return 42\n")

    store = SQLiteStore(tmp_path / "codewiki.sqlite3")
    repo = store.upsert_repo(RepoScanner().describe(str(repo_dir)))
    AnalysisService(store=store).analyze(repo.id)
    store.replace_code_chunks_for_files(
        repo.id,
        ["service.py"],
        GraphRAGRetriever(store=store).build_source_chunks(
            repo_id=repo.id,
            repo_path=repo.path,
            nodes=store.get_graph(repo.id)[0],
        ),
    )

    service_path.unlink()
    result = IncrementalUpdater(store=store).update(repo.id)
    nodes, _edges = store.get_graph(repo.id)

    assert result.plan.deleted_files == ["service.py"]
    assert not any(node.file_path == "service.py" for node in nodes)
    assert not any(chunk.file_path == "service.py" for chunk in store.list_code_chunks(repo.id))
