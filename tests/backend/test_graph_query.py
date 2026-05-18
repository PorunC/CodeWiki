from pathlib import Path

from backend.app.database import SQLiteStore
from backend.app.services.analyzer import AnalysisService
from backend.app.services.graph.query import GraphQueryService
from backend.app.services.repo_scanner import RepoScanner


def test_symbol_fts_search_callers_impact_and_explore(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "service.py").write_text(
        "\n".join(
            [
                "def helper():",
                "    return 1",
                "",
                "def handler():",
                "    return helper()",
            ]
        )
        + "\n"
    )

    store = SQLiteStore(tmp_path / "codewiki.sqlite3")
    repo = store.upsert_repo(RepoScanner().describe(str(repo_dir)))
    AnalysisService(store=store).analyze(repo.id)

    hits = store.search_code_nodes(repo.id, "helper", types=["function"], limit=5)
    assert hits
    assert hits[0].node.name == "helper"

    service = GraphQueryService(store=store)
    callers = service.callers(repo.id, "helper")
    assert any(item.source.name == "handler" for item in callers)

    impact = service.impact(repo.id, "helper", depth=2)
    assert any(node.name == "handler" for node in impact.nodes)

    explore = service.explore(repo.id, "handler helper", max_files=4)
    assert "def helper" in explore.text
    assert "def handler" in explore.text


def test_affected_analysis_finds_transitive_tests(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    tests_dir = repo_dir / "tests"
    tests_dir.mkdir(parents=True)
    (repo_dir / "service.py").write_text("def helper():\n    return 1\n")
    (repo_dir / "api.py").write_text(
        "from service import helper\n\n"
        "def handler():\n"
        "    return helper()\n"
    )
    (tests_dir / "test_api.py").write_text(
        "from api import handler\n\n"
        "def test_handler():\n"
        "    assert handler() == 1\n"
    )

    store = SQLiteStore(tmp_path / "codewiki.sqlite3")
    repo = store.upsert_repo(RepoScanner().describe(str(repo_dir)))
    AnalysisService(store=store).analyze(repo.id)

    affected = GraphQueryService(store=store).affected(repo.id, ["service.py"], depth=5)

    assert "api.py" in affected.affected_files
    assert "tests/test_api.py" in affected.affected_tests
