import subprocess
from pathlib import Path

import pytest

from backend.app.config import get_settings
from backend.app.database import DocPageRecord, SQLiteStore
from backend.app.services.analyzer import AnalysisService
from backend.app.services.ast_parser import AstParser
from backend.app.services.graphrag import GraphRAGRetriever
from backend.app.services.incremental import IncrementalUpdater
from backend.app.services.repo_metadata import read_repo_metadata
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


def test_incremental_update_preserves_file_symbol_contains_edges(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "service.py").write_text("def answer():\n    return 42\n", encoding="utf-8")
    (repo_dir / "api.py").write_text(
        "from service import answer\n\n"
        "def handler():\n"
        "    return answer()\n",
        encoding="utf-8",
    )

    store = SQLiteStore(tmp_path / "codewiki.sqlite3")
    repo = store.upsert_repo(RepoScanner().describe(str(repo_dir)))
    AnalysisService(store=store).analyze(repo.id)
    _nodes_before, edges_before = store.get_graph(repo.id)
    contains_before = sum(1 for edge in edges_before if edge.type == "contains")

    (repo_dir / "api.py").write_text(
        "from service import answer\n\n"
        "def handler():\n"
        "    return answer() + 1\n",
        encoding="utf-8",
    )
    IncrementalUpdater(store=store).update(repo.id)
    nodes_after, edges_after = store.get_graph(repo.id)
    contains_after = sum(1 for edge in edges_after if edge.type == "contains")
    service_file = next(node for node in nodes_after if node.type == "file" and node.file_path == "service.py")
    answer = next(node for node in nodes_after if node.name == "answer")

    assert contains_after == contains_before
    assert any(
        edge.type == "contains"
        and edge.source_id == service_file.id
        and edge.target_id == answer.id
        for edge in edges_after
    )


def test_incremental_update_uses_metadata_git_diff_candidates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage_dir = tmp_path / "storage"
    monkeypatch.setenv("CODEWIKI_STORAGE_DIR", str(storage_dir))
    get_settings.cache_clear()

    try:
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        _git(repo_dir, "init")
        _git(repo_dir, "config", "user.email", "test@example.com")
        _git(repo_dir, "config", "user.name", "Test User")
        (repo_dir / "service.py").write_text("def answer():\n    return 42\n")
        (repo_dir / "old.py").write_text("def legacy():\n    return 'old'\n")
        _git(repo_dir, "add", ".")
        _git(repo_dir, "commit", "-m", "initial")
        initial_commit = _git_output(repo_dir, "rev-parse", "HEAD")

        store = SQLiteStore(tmp_path / "codewiki.sqlite3")
        scanner = RepoScanner()
        parser = AstParser(cache_dir=tmp_path / "cache" / "ast")
        repo = store.upsert_repo(scanner.describe(str(repo_dir)))
        AnalysisService(store=store, scanner=scanner, parser=parser).analyze(repo.id)

        initial_metadata = read_repo_metadata(repo.id)
        assert initial_metadata is not None
        assert initial_metadata.commit_hash == initial_commit
        assert (storage_dir / "repos" / repo.id / "metadata.json").is_file()

        (repo_dir / "service.py").write_text("def answer():\n    return 43\n")
        (repo_dir / "old.py").unlink()
        (repo_dir / "util.py").write_text("def helper():\n    return 'ok'\n")
        _git(repo_dir, "add", "-A")
        _git(repo_dir, "commit", "-m", "update files")
        updated_commit = _git_output(repo_dir, "rev-parse", "HEAD")

        result = IncrementalUpdater(store=store, scanner=scanner, parser=parser).update(repo.id)
        updated_metadata = read_repo_metadata(repo.id)

        assert result.plan.detection_strategy == "git_diff+sha256"
        assert result.plan.base_commit == initial_commit
        assert result.plan.head_commit == updated_commit
        assert result.plan.changed_files == ["service.py"]
        assert result.plan.new_files == ["util.py"]
        assert result.plan.deleted_files == ["old.py"]
        assert result.parsed_file_count == 2
        assert updated_metadata is not None
        assert updated_metadata.commit_hash == updated_commit
        assert store.get_repo(repo.id).commit_hash == updated_commit
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_incremental_update_with_wiki_regeneration_refreshes_stale_pages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    service_path = repo_dir / "service.py"
    service_path.write_bytes(b"def answer():\n    return 42\n")

    store = SQLiteStore(tmp_path / "codewiki.sqlite3")
    repo = store.upsert_repo(RepoScanner().describe(str(repo_dir)))
    AnalysisService(store=store).analyze(repo.id)
    store.upsert_doc_page(
        DocPageRecord(
            id="page-service",
            repo_id=repo.id,
            slug="service",
            title="Service",
            parent_slug=None,
            markdown="# Service\n",
            source_refs=[{"file_path": "service.py", "start_line": 1, "end_line": 2}],
            graph_refs=[],
            status="generated",
            updated_at=None,
        )
    )

    captured: dict[str, object] = {}

    async def fake_regenerate_stale_wiki_pages(
        fake_store: SQLiteStore,
        repo_id: str,
        stale_pages: list[str],
    ) -> dict[str, object]:
        captured["store"] = fake_store
        captured["repo_id"] = repo_id
        captured["stale_pages"] = stale_pages
        return {"requested": True, "pages": [{"slug": slug, "status": "generated"} for slug in stale_pages], "errors": []}

    monkeypatch.setattr(
        "backend.app.services.incremental.updater.regenerate_stale_wiki_pages",
        fake_regenerate_stale_wiki_pages,
    )
    service_path.write_bytes(b"def answer():\n    return 43\n")

    result, wiki_regeneration = await IncrementalUpdater(store=store).update_with_wiki_regeneration(repo.id)

    assert result.stale_pages == ["service"]
    assert captured == {"store": store, "repo_id": repo.id, "stale_pages": ["service"]}
    assert wiki_regeneration["requested"] is True
    assert wiki_regeneration["pages"] == [{"slug": "service", "status": "generated"}]


def _git(repo_dir: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo_dir), *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _git_output(repo_dir: Path, *args: str) -> str:
    process = subprocess.run(
        ["git", "-C", str(repo_dir), *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return process.stdout.strip()
