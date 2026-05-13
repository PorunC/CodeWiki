import json
from pathlib import Path

from click.testing import CliRunner

from backend.app.cli import main
from backend.app.config import get_settings
from backend.app.db.store import get_store


def test_cli_registers_and_lists_repositories(tmp_path: Path, monkeypatch) -> None:
    _configure_database(tmp_path, monkeypatch)
    repo_dir = _repo(tmp_path)
    runner = CliRunner()

    add_result = runner.invoke(
        main,
        ["repos", "add", str(repo_dir), "--name", "repo", "--json"],
    )

    assert add_result.exit_code == 0, add_result.output
    repo = json.loads(add_result.output)
    assert repo["name"] == "repo"
    assert repo["path"] == str(repo_dir.resolve())

    list_result = runner.invoke(main, ["repos", "list", "--json"])

    assert list_result.exit_code == 0, list_result.output
    repos = json.loads(list_result.output)
    assert [item["id"] for item in repos] == [repo["id"]]


def test_cli_scans_repository_as_json(tmp_path: Path, monkeypatch) -> None:
    _configure_database(tmp_path, monkeypatch)
    repo_dir = _repo(tmp_path)
    runner = CliRunner()

    result = runner.invoke(main, ["repos", "scan", str(repo_dir), "--json"])

    assert result.exit_code == 0, result.output
    scan = json.loads(result.output)
    assert scan["scanned_count"] == 2
    assert {file["path"] for file in scan["files"]} == {"README.md", "main.py"}


def test_cli_runs_analysis(tmp_path: Path, monkeypatch) -> None:
    _configure_database(tmp_path, monkeypatch)
    repo_dir = _repo(tmp_path)
    runner = CliRunner()
    add_result = runner.invoke(main, ["repos", "add", str(repo_dir), "--json"])
    repo_id = json.loads(add_result.output)["id"]

    result = runner.invoke(main, ["analyze", repo_id, "--json"])

    assert result.exit_code == 0, result.output
    analysis = json.loads(result.output)
    assert analysis["status"] == "done"
    assert analysis["node_count"] >= 2
    assert analysis["edge_count"] >= 1


def test_cli_analyzes_current_directory_without_repo_id(tmp_path: Path, monkeypatch) -> None:
    _configure_database(tmp_path, monkeypatch)
    repo_dir = _repo(tmp_path)
    monkeypatch.chdir(repo_dir)
    runner = CliRunner()

    result = runner.invoke(main, ["analyze", "--json"])

    assert result.exit_code == 0, result.output
    analysis = json.loads(result.output)
    assert analysis["status"] == "done"
    repos = get_store().list_repos()
    assert len(repos) == 1
    assert repos[0].path == str(repo_dir.resolve())


def test_cli_accepts_repo_name_instead_of_id(tmp_path: Path, monkeypatch) -> None:
    _configure_database(tmp_path, monkeypatch)
    repo_dir = _repo(tmp_path)
    runner = CliRunner()
    add_result = runner.invoke(main, ["repos", "add", str(repo_dir), "--name", "friendly", "--json"])
    assert add_result.exit_code == 0, add_result.output

    result = runner.invoke(main, ["analyze", "friendly", "--json"])

    assert result.exit_code == 0, result.output
    analysis = json.loads(result.output)
    assert analysis["status"] == "done"


def _repo(tmp_path: Path) -> Path:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "README.md").write_text("# Repo\n")
    (repo_dir / "main.py").write_text("def answer():\n    return 42\n")
    return repo_dir


def _configure_database(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv(
        "CODEWIKI_DATABASE_URL",
        f"sqlite+aiosqlite:///{tmp_path / 'codewiki.sqlite3'}",
    )
    get_settings.cache_clear()
    get_store.cache_clear()
