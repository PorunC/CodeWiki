import json
import shutil
import subprocess
from inspect import signature
from pathlib import Path

import pytest
from click.testing import CliRunner

from backend.app.cli import main
from backend.app.config import get_settings
from backend.app.database import DocPageRecord
from backend.app.db.store import get_store


def _separate_stderr_runner() -> CliRunner:
    if "mix_stderr" in signature(CliRunner).parameters:
        return CliRunner(mix_stderr=False)
    return CliRunner()


def test_cli_help_lists_serve_command() -> None:
    runner = CliRunner()

    result = runner.invoke(main, ["--help"])

    assert result.exit_code == 0, result.output
    assert "config" in result.output
    assert "mcp" in result.output
    assert "serve" in result.output
    assert "Lite mode keeps a no-LLM index" in result.output
    assert "codewiki lite index ." in result.output
    assert "codewiki mcp --lite --path ." in result.output


def test_cli_registers_and_lists_repositories(tmp_path: Path, monkeypatch) -> None:
    _configure_database(tmp_path, monkeypatch)
    repo_dir = _repo(tmp_path)
    runner = _separate_stderr_runner()

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


def test_cli_lists_file_tree_for_registered_repo(tmp_path: Path, monkeypatch) -> None:
    _configure_database(tmp_path, monkeypatch)
    repo_dir = _repo(tmp_path)
    runner = CliRunner()
    add_result = runner.invoke(main, ["repos", "add", str(repo_dir), "--json"])
    repo_id = json.loads(add_result.output)["id"]

    result = runner.invoke(main, ["files", "tree", repo_id, "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["repo_id"] == repo_id
    assert {file["path"] for file in payload["files"]} == {"README.md", "main.py"}
    assert payload["root"]["children"][0]["name"] == "main.py"


def test_cli_deletes_registered_repository(tmp_path: Path, monkeypatch) -> None:
    _configure_database(tmp_path, monkeypatch)
    repo_dir = _repo(tmp_path)
    runner = CliRunner()
    add_result = runner.invoke(main, ["repos", "add", str(repo_dir), "--json"])
    repo_id = json.loads(add_result.output)["id"]

    result = runner.invoke(main, ["repos", "delete", repo_id, "--json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {"deleted": True, "repo_id": repo_id}
    assert get_store().get_repo(repo_id) is None


def test_cli_reads_wiki_pages_by_language(tmp_path: Path, monkeypatch) -> None:
    _configure_database(tmp_path, monkeypatch)
    repo_dir = _repo(tmp_path)
    runner = CliRunner()
    add_result = runner.invoke(main, ["repos", "add", str(repo_dir), "--json"])
    repo_id = json.loads(add_result.output)["id"]
    store = get_store()
    store.save_doc_catalog(
        repo_id,
        title="文档",
        structure={"items": [{"slug": "overview", "title": "概览"}]},
        language_code="zh",
        catalog_id="catalog-zh",
    )
    store.upsert_doc_page(
        DocPageRecord(
            id="page-zh",
            repo_id=repo_id,
            language_code="zh",
            slug="overview",
            title="概览",
            parent_slug=None,
            markdown="# 概览\n",
            source_refs=[],
            graph_refs=[],
            status="generated",
            updated_at="2026-05-26T00:00:00Z",
        )
    )

    list_result = runner.invoke(main, ["wiki", "list", repo_id, "--language", "zh", "--json"])
    read_result = runner.invoke(main, ["wiki", "read", "overview", repo_id, "--language", "zh"])

    assert list_result.exit_code == 0, list_result.output
    payload = json.loads(list_result.output)
    assert payload["catalog"]["language_code"] == "zh"
    assert payload["pages"][0]["title"] == "概览"
    assert read_result.exit_code == 0, read_result.output
    assert read_result.output == "# 概览\n\n"


def test_cli_registers_git_url(tmp_path: Path, monkeypatch) -> None:
    if shutil.which("git") is None:
        pytest.skip("git executable is required for clone integration test")

    _configure_database(tmp_path, monkeypatch)
    source_repo = _git_repo(tmp_path / "source-repo")
    runner = CliRunner()

    result = runner.invoke(
        main,
        ["repos", "add", source_repo.resolve().as_uri(), "--json"],
    )

    assert result.exit_code == 0, result.output
    repo = json.loads(result.output)
    assert repo["name"] == "source-repo"
    assert repo["source_type"] == "git"
    assert repo["git_url"] == source_repo.resolve().as_uri()
    assert Path(repo["path"]).is_dir()


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


def test_cli_lite_indexes_and_queries_project_local_database(tmp_path: Path) -> None:
    repo_dir = tmp_path / "lite-repo"
    repo_dir.mkdir()
    (repo_dir / "app.py").write_text(
        "def helper(x):\n"
        "    return x + 1\n"
        "\n"
        "def main():\n"
        "    return helper(41)\n",
        encoding="utf-8",
    )
    runner = CliRunner()

    index_result = runner.invoke(main, ["lite", "index", str(repo_dir), "--json"])
    assert index_result.exit_code == 0, index_result.output
    index_payload = json.loads(index_result.output)
    assert index_payload["status"] == "done"
    assert Path(index_payload["database_path"]) == repo_dir / ".codewiki" / "codewiki-lite.sqlite3"

    query_result = runner.invoke(main, ["lite", "query", "helper", str(repo_dir), "--json"])
    assert query_result.exit_code == 0, query_result.output
    hits = json.loads(query_result.output)
    assert hits[0]["node"]["name"] == "helper"

    callers_result = runner.invoke(main, ["lite", "callers", "helper", str(repo_dir), "--json"])
    assert callers_result.exit_code == 0, callers_result.output
    callers = json.loads(callers_result.output)
    assert callers[0]["source"]["name"] == "main"

    callees_result = runner.invoke(main, ["lite", "callees", "main", str(repo_dir), "--json"])
    assert callees_result.exit_code == 0, callees_result.output
    callees = json.loads(callees_result.output)
    assert callees[0]["target"]["name"] == "helper"

    impact_result = runner.invoke(main, ["lite", "impact", "helper", str(repo_dir), "--json"])
    assert impact_result.exit_code == 0, impact_result.output
    impact = json.loads(impact_result.output)
    assert any(node["name"] == "main" for node in impact["nodes"])

    files_result = runner.invoke(main, ["lite", "files", str(repo_dir), "--json"])
    assert files_result.exit_code == 0, files_result.output
    files_payload = json.loads(files_result.output)
    assert files_payload["source"] == "index"
    assert [file["path"] for file in files_payload["files"]] == ["app.py"]

    status_result = runner.invoke(main, ["lite", "status", str(repo_dir), "--json"])
    assert status_result.exit_code == 0, status_result.output
    assert json.loads(status_result.output)["pending_sync"] is False

    (repo_dir / "app.py").write_text(
        "def helper(x):\n"
        "    return x + 2\n"
        "\n"
        "def main():\n"
        "    return helper(40)\n",
        encoding="utf-8",
    )
    stale_status_result = runner.invoke(main, ["lite", "status", str(repo_dir), "--json"])
    assert stale_status_result.exit_code == 0, stale_status_result.output
    stale_status = json.loads(stale_status_result.output)
    assert stale_status["pending_sync"] is True
    assert stale_status["changed_files"] == ["app.py"]

    trace_result = runner.invoke(main, ["lite", "trace", "main", "helper", str(repo_dir)])
    assert trace_result.exit_code == 0, trace_result.output
    assert "main -> helper" in trace_result.output
    assert "-> calls" in trace_result.output

    uninit_result = runner.invoke(main, ["lite", "uninit", str(repo_dir), "--force", "--json"])
    assert uninit_result.exit_code == 0, uninit_result.output
    assert json.loads(uninit_result.output)["deleted"] is True
    assert not (repo_dir / ".codewiki").exists()


def test_cli_lite_agents_install_claude_local_config(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    runner = CliRunner()

    result = runner.invoke(
        main,
        [
            "lite",
            "agents",
            "install",
            str(repo_dir),
            "--target",
            "claude",
            "--location",
            "local",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload[0]["target"] == "claude"
    assert (repo_dir / ".mcp.json").exists()
    mcp_config = json.loads((repo_dir / ".mcp.json").read_text(encoding="utf-8"))
    server = mcp_config["mcpServers"]["codewiki-lite"]
    assert server["command"] == "codewiki"
    assert server["args"] == ["mcp", "--lite", "--path", str(repo_dir.resolve())]

    settings = json.loads((repo_dir / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert "mcp__codewiki-lite__codewiki_context" in settings["permissions"]["allow"]
    instructions = (repo_dir / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")
    assert "<!-- CODEWIKI_LITE_START -->" in instructions
    assert "CodeWiki Lite" in instructions


def test_cli_lite_agents_install_codex_global_config(tmp_path: Path, monkeypatch) -> None:
    repo_dir = tmp_path / "repo"
    home_dir = tmp_path / "home"
    repo_dir.mkdir()
    home_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))
    runner = CliRunner()

    result = runner.invoke(
        main,
        [
            "lite",
            "agents",
            "install",
            str(repo_dir),
            "--target",
            "codex",
            "--location",
            "global",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    config = (home_dir / ".codex" / "config.toml").read_text(encoding="utf-8")
    assert "[mcp_servers.codewiki-lite]" in config
    assert 'command = "codewiki"' in config
    assert f'"{repo_dir.resolve()}"' in config
    instructions = (home_dir / ".codex" / "AGENTS.md").read_text(encoding="utf-8")
    assert "<!-- CODEWIKI_LITE_START -->" in instructions
    assert "codewiki lite sync ." in instructions


def test_cli_analysis_progress_goes_to_stderr_with_json_stdout(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _configure_database(tmp_path, monkeypatch)
    repo_dir = _repo(tmp_path)
    runner = _separate_stderr_runner()
    add_result = runner.invoke(main, ["repos", "add", str(repo_dir), "--json"])
    repo_id = json.loads(add_result.output)["id"]

    result = runner.invoke(main, ["analyze", repo_id, "--progress", "--json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["status"] == "done"
    assert "PROGRESS scan start" in result.stderr
    assert "PROGRESS parse" in result.stderr
    assert "PROGRESS persist done" in result.stderr


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


def test_cli_config_sets_env_values(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    runner = CliRunner()

    result = runner.invoke(
        main,
        [
            "config",
            "--env-file",
            str(env_file),
            "--set",
            "CODEWIKI_LLM__DEFAULT__MODEL=provider/test-model",
            "--set",
            "CODEWIKI_WIKI_TRANSLATION_LANGUAGES=zh,ja",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["created"] is True
    assert payload["updated"] == {
        "CODEWIKI_LLM__DEFAULT__MODEL": "provider/test-model",
        "CODEWIKI_WIKI_TRANSLATION_LANGUAGES": "zh,ja",
    }
    env_text = env_file.read_text(encoding="utf-8")
    assert "CODEWIKI_LLM__DEFAULT__MODEL=provider/test-model" in env_text
    assert "CODEWIKI_WIKI_TRANSLATION_LANGUAGES=zh,ja" in env_text


def test_cli_config_profile_options_mask_secret_output(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    runner = CliRunner()

    result = runner.invoke(
        main,
        [
            "config",
            "--env-file",
            str(env_file),
            "--profile",
            "qa",
            "--model",
            "provider/qa-model",
            "--max-tokens",
            "8000",
            "--api-key",
            "secret-key",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "secret-key" not in result.output
    assert "********" in result.output
    env_text = env_file.read_text(encoding="utf-8")
    assert "CODEWIKI_LLM__PROFILES__QA__MODEL=provider/qa-model" in env_text
    assert "CODEWIKI_LLM__PROFILES__QA__MAX_TOKENS=8000" in env_text
    assert "CODEWIKI_LLM__PROFILES__QA__API_KEY=secret-key" in env_text


def test_cli_config_get_and_list_values(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "CODEWIKI_LLM__DEFAULT__MODEL=provider/test-model",
                "CODEWIKI_LLM__DEFAULT__API_KEY=secret-key",
                "IGNORED=value",
            ]
        ),
        encoding="utf-8",
    )
    runner = CliRunner()

    get_result = runner.invoke(
        main,
        [
            "config",
            "--env-file",
            str(env_file),
            "--get",
            "CODEWIKI_LLM__DEFAULT__API_KEY",
            "--json",
        ],
    )

    assert get_result.exit_code == 0, get_result.output
    assert json.loads(get_result.output)["values"] == {
        "CODEWIKI_LLM__DEFAULT__API_KEY": "********"
    }

    list_result = runner.invoke(main, ["config", "--env-file", str(env_file), "--list", "--json"])

    assert list_result.exit_code == 0, list_result.output
    listed = json.loads(list_result.output)["values"]
    assert listed == {
        "CODEWIKI_LLM__DEFAULT__MODEL": "provider/test-model",
        "CODEWIKI_LLM__DEFAULT__API_KEY": "********",
    }


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
    monkeypatch.setenv("CODEWIKI_STORAGE_DIR", str(tmp_path / "storage"))
    monkeypatch.delenv("CODEWIKI_LLM__DEFAULT__API_KEY", raising=False)
    monkeypatch.delenv("CODEWIKI_LLM__DEFAULT__ENDPOINT", raising=False)
    monkeypatch.delenv("CODEWIKI_LLM__DEFAULT__PROVIDER_TYPE", raising=False)
    monkeypatch.setenv("CODEWIKI_LLM__DEFAULT__MODEL", "provider/strong-coding-model")
    get_settings.cache_clear()
    get_store.cache_clear()


def _git_repo(repo_dir: Path) -> Path:
    repo_dir.mkdir()
    _git(repo_dir, "init")
    _git(repo_dir, "config", "user.email", "test@example.com")
    _git(repo_dir, "config", "user.name", "Test User")
    (repo_dir / "README.md").write_text("# Repo\n")
    _git(repo_dir, "add", "README.md")
    _git(repo_dir, "commit", "-m", "initial")
    return repo_dir


def _git(repo_dir: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo_dir), *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
