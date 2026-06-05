import csv
import sys
from pathlib import Path

import pytest

from scripts import benchmark_repos
from scripts import benchmark_lite_mode


def test_default_run_repos_match_layered_baseline() -> None:
    repos = benchmark_repos.select_repos(None, mode="run", allow_xl=False)

    assert [repo.key for repo in repos] == [
        "react",
        "vscode",
        "superset",
        "kubernetes",
        "elasticsearch",
    ]


def test_prepare_defaults_include_clone_pack_without_xl() -> None:
    repos = benchmark_repos.select_repos(None, mode="prepare", allow_xl=False)

    assert {repo.key for repo in repos} == {
        "react",
        "vscode",
        "superset",
        "kubernetes",
        "rust",
        "elasticsearch",
        "large-ts-monorepo",
    }
    assert all(not repo.xl for repo in repos)


def test_xl_repos_require_explicit_acknowledgement() -> None:
    with pytest.raises(SystemExit, match="XL repositories are disabled"):
        benchmark_repos.select_repos("nixpkgs", mode="run", allow_xl=False)


def test_clone_command_always_uses_shallow_depth_one() -> None:
    repo = benchmark_repos.REPOS_BY_KEY["react"]

    assert benchmark_repos.clone_command(repo, Path("/tmp/react")) == [
        "git",
        "clone",
        "--depth",
        "1",
        "--progress",
        "https://github.com/facebook/react.git",
        "/tmp/react",
    ]


def test_repository_benchmark_uses_local_typescript_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CODEWIKI_CLI", raising=False)
    monkeypatch.delenv("NPM", raising=False)

    assert benchmark_repos.codewiki_command(["--version"]) == [
        "npm",
        "--prefix",
        str(benchmark_repos.PROJECT_ROOT / "backend-ts"),
        "exec",
        "--",
        "tsx",
        "--",
        "src/cli.ts",
        "--version",
    ]


def test_benchmark_cli_command_can_be_overridden(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CODEWIKI_CLI", "node dist/cli.js")

    assert benchmark_repos.codewiki_command(["--version"]) == [
        "node",
        "dist/cli.js",
        "--version",
    ]
    assert benchmark_lite_mode.codewiki_command(["lite", "status", "."]) == [
        "node",
        "dist/cli.js",
        "lite",
        "status",
        ".",
    ]


def test_summary_csv_flattens_payload_metrics(tmp_path) -> None:
    csv_path = tmp_path / "summary.csv"
    benchmark_repos.write_summary_csv(
        csv_path,
        [
            {
                "repo_key": "react",
                "tier": "S",
                "scenario": "cold",
                "elapsed_seconds": 12.345,
                "exit_code": 0,
                "timed_out": False,
                "payload": {
                    "mode": "full",
                    "scanned_count": 10,
                    "parsed_file_count": 8,
                    "reused_file_count": 0,
                    "node_count": 20,
                    "edge_count": 30,
                    "community_count": 4,
                    "chunk_count": 15,
                    "errors": [{"path": "bad.ts"}],
                },
            }
        ],
    )

    rows = list(csv.DictReader(csv_path.open(encoding="utf-8")))
    assert rows[0]["repo_key"] == "react"
    assert rows[0]["mode"] == "full"
    assert rows[0]["error_count"] == "1"


def test_command_count_for_scenarios_matches_cli_steps() -> None:
    assert benchmark_repos.command_count_for_scenarios(("cold", "warm", "small-delta")) == 4
    assert benchmark_repos.command_count_for_scenarios(("warm",)) == 1


def test_format_duration_is_compact() -> None:
    assert benchmark_repos.format_duration(9.876) == "9.9s"
    assert benchmark_repos.format_duration(125) == "2m05s"
    assert benchmark_repos.format_duration(3661) == "1h01m01s"


def test_split_progress_message_separates_status_from_detail() -> None:
    status, detail = benchmark_repos.split_progress_message(
        "parse 10/100 (10.0%) path=src/vs/workbench/file.ts"
    )

    assert status == "parse 10/100 (10.0%)"
    assert detail == "path=src/vs/workbench/file.ts"


def test_run_command_emits_periodic_status(tmp_path) -> None:
    statuses: list[float] = []

    result = benchmark_repos.run_command(
        [sys.executable, "-c", "import time; time.sleep(0.25); print('{}')"],
        cwd=tmp_path,
        timeout_seconds=5,
        status_interval_seconds=0.1,
        on_status=statuses.append,
    )

    assert result.exit_code == 0
    assert result.stdout.strip() == "{}"
    assert statuses


def test_lite_benchmark_generates_synthetic_repo(tmp_path: Path) -> None:
    repo = tmp_path / "synthetic"

    benchmark_lite_mode.generate_python_repo(repo, files=4, fanout=2)

    assert (repo / "pkg" / "module_0000.py").is_file()
    text = (repo / "pkg" / "module_0000.py").read_text(encoding="utf-8")
    assert "from pkg.module_0001 import func_1" in text
    assert "from pkg.module_0002 import func_2" in text
    assert (repo / "tests" / "test_smoke.py").is_file()


def test_lite_benchmark_summary_flattens_metrics(tmp_path: Path) -> None:
    csv_path = tmp_path / "lite-summary.csv"
    benchmark_lite_mode.write_summary(
        csv_path,
        [
            benchmark_lite_mode.LiteCommandResult(
                scenario="cold-index",
                command=["codewiki", "lite", "index", "."],
                elapsed_seconds=1.25,
                exit_code=0,
                payload={"node_count": 10, "edge_count": 20, "pending_files": ["a.py"]},
                stderr_tail="",
            )
        ],
        files=4,
        fanout=2,
    )

    rows = list(csv.DictReader(csv_path.open(encoding="utf-8")))
    assert rows[0]["scenario"] == "cold-index"
    assert rows[0]["node_count"] == "10"
    assert rows[0]["pending_files"] == "1"
