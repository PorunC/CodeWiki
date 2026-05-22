"""Layered repository benchmark runner for Code Wiki.

The runner intentionally defaults to the medium-safe baseline sequence so local
test environments do not jump straight to XL repositories.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shlex
import sqlite3
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from tqdm import tqdm


PROJECT_ROOT = Path(__file__).resolve().parents[1]
GIT_CLONE_ARGS = ("clone", "--depth", "1", "--progress")


@dataclass(frozen=True)
class BenchRepo:
    key: str
    tier: str
    slug: str
    url: str
    language_hint: str
    default_run: bool = False
    default_clone: bool = False
    xl: bool = False
    research: bool = False

    @property
    def dirname(self) -> str:
        return self.slug.rsplit("/", 1)[1]


REPOS: tuple[BenchRepo, ...] = (
    BenchRepo(
        key="react",
        tier="S",
        slug="facebook/react",
        url="https://github.com/facebook/react.git",
        language_hint="ts",
        default_run=True,
        default_clone=True,
    ),
    BenchRepo(
        key="vscode",
        tier="M",
        slug="microsoft/vscode",
        url="https://github.com/microsoft/vscode.git",
        language_hint="ts",
        default_run=True,
        default_clone=True,
    ),
    BenchRepo(
        key="superset",
        tier="M",
        slug="apache/superset",
        url="https://github.com/apache/superset.git",
        language_hint="py",
        default_run=True,
        default_clone=True,
    ),
    BenchRepo(
        key="kubernetes",
        tier="L",
        slug="kubernetes/kubernetes",
        url="https://github.com/kubernetes/kubernetes.git",
        language_hint="go",
        default_run=True,
        default_clone=True,
    ),
    BenchRepo(
        key="rust",
        tier="L",
        slug="rust-lang/rust",
        url="https://github.com/rust-lang/rust.git",
        language_hint="rs",
        default_clone=True,
    ),
    BenchRepo(
        key="elasticsearch",
        tier="L",
        slug="elastic/elasticsearch",
        url="https://github.com/elastic/elasticsearch.git",
        language_hint="java",
        default_run=True,
        default_clone=True,
    ),
    BenchRepo(
        key="nixpkgs",
        tier="XL",
        slug="NixOS/nixpkgs",
        url="https://github.com/NixOS/nixpkgs.git",
        language_hint="nix",
        xl=True,
    ),
    BenchRepo(
        key="odoo",
        tier="XL",
        slug="odoo/odoo",
        url="https://github.com/odoo/odoo.git",
        language_hint="py",
        xl=True,
    ),
    BenchRepo(
        key="codescalebench",
        tier="benchmark",
        slug="sourcegraph/CodeScaleBench",
        url="https://github.com/sourcegraph/CodeScaleBench.git",
        language_hint="mixed",
        research=True,
    ),
    BenchRepo(
        key="large-ts-monorepo",
        tier="benchmark",
        slug="nrwl/large-ts-monorepo",
        url="https://github.com/nrwl/large-ts-monorepo.git",
        language_hint="ts",
        default_clone=True,
        research=True,
    ),
    BenchRepo(
        key="dypybench",
        tier="benchmark",
        slug="sola-st/DyPyBench",
        url="https://github.com/sola-st/DyPyBench.git",
        language_hint="py",
        research=True,
    ),
)

REPOS_BY_KEY = {repo.key: repo for repo in REPOS}
DEFAULT_SCENARIOS = ("cold", "warm", "small-delta")
DEFAULT_STATUS_INTERVAL_SECONDS = 30.0
DATABASE_WRITE_TABLES = (
    ("repo", "repos"),
    ("analysis_run", "runs"),
    ("code_node", "nodes"),
    ("code_edge", "edges"),
    ("graph_community", "communities"),
    ("graph_community_edge", "community_edges"),
    ("code_chunk", "chunks"),
    ("code_chunk_embedding", "embeddings"),
    ("doc_catalog", "catalogs"),
    ("doc_page", "pages"),
    ("llm_run", "llm_runs"),
)
DELTA_CONTENT = {
    "go": ("codewiki_bench_delta.go", "package main\n\nconst CodeWikiBenchDelta = 1\n"),
    "java": (
        "CodeWikiBenchDelta.java",
        "class CodeWikiBenchDelta {\n    static final int VALUE = 1;\n}\n",
    ),
    "py": ("codewiki_bench_delta.py", "CODEWIKI_BENCH_DELTA = 1\n"),
    "rs": ("codewiki_bench_delta.rs", "pub const CODEWIKI_BENCH_DELTA: i32 = 1;\n"),
    "ts": ("codewiki_bench_delta.ts", "export const codewikiBenchDelta = 1;\n"),
}


@dataclass(frozen=True)
class CommandResult:
    command: list[str]
    elapsed_seconds: float
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False


@dataclass(frozen=True)
class DatabaseWriteStats:
    total_rows: int
    table_counts: dict[str, int]
    error: str | None = None


class ProgressReporter:
    def __init__(self, *, total_steps: int, label: str) -> None:
        self.total_steps = max(total_steps, 1)
        self.is_tty = sys.stderr.isatty()
        self.bar = tqdm(
            total=self.total_steps,
            desc=label,
            unit="step",
            dynamic_ncols=True,
            leave=True,
            position=0,
            disable=not self.is_tty,
        )
        self.status = tqdm(
            total=0,
            bar_format="{desc}",
            dynamic_ncols=True,
            leave=False,
            position=1,
            disable=not self.is_tty,
        )
        self.detail = tqdm(
            total=0,
            bar_format="{desc}",
            dynamic_ncols=True,
            leave=False,
            position=2,
            disable=not self.is_tty,
        )

    def start(self, message: str) -> None:
        self._set_status(status=message)
        self.bar.write(f"START {message}")

    def done(self, message: str, *, elapsed_seconds: float, exit_code: int) -> None:
        status = "OK" if exit_code == 0 else f"FAIL({exit_code})"
        self.bar.update(1)
        self._set_status(status=f"{status} {message}", detail=format_duration(elapsed_seconds))
        self.bar.write(f"{status} {message} ({format_duration(elapsed_seconds)})")

    def skipped(self, message: str) -> None:
        self.bar.update(1)
        self._set_status(status=f"SKIP {message}")
        self.bar.write(f"SKIP {message}")

    def message(self, message: str) -> None:
        self.bar.write(message)

    def running(
        self,
        message: str,
        *,
        elapsed_seconds: float,
        database_stats: DatabaseWriteStats | None = None,
    ) -> None:
        detail = f"elapsed {format_duration(elapsed_seconds)}"
        if database_stats is not None:
            detail = f"{detail}; {format_database_write_stats(database_stats)}"
        self._set_status(status=f"RUNNING {message}", detail=detail)

    def analysis_progress(self, message: str) -> None:
        status, detail = split_progress_message(message.removeprefix("PROGRESS ").strip())
        self._set_status(status=status, detail=detail)

    def _set_status(self, *, status: str, detail: str | None = None) -> None:
        if self.is_tty:
            self.status.set_description_str(f"status: {status}")
            self.detail.set_description_str(f"detail: {detail or ''}")

    def close(self) -> None:
        self.detail.close()
        self.status.close()
        self.bar.close()


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "list":
        list_repos()
        return 0

    root = Path(args.root).expanduser().resolve()
    selected = select_repos(args.repos, mode=args.command, allow_xl=args.yes_xl)

    if args.command in {"prepare", "all"}:
        prepare_repos(root, selected, dry_run=args.dry_run)

    if args.command in {"run", "all"}:
        scenarios = tuple(args.scenarios.split(","))
        run_benchmarks(
            root,
            selected,
            scenarios=scenarios,
            timeout_minutes=args.timeout_minutes,
            status_interval_seconds=args.status_interval,
            dry_run=args.dry_run,
        )

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run layered Code Wiki repository benchmarks.")
    parser.add_argument(
        "--root",
        default="~/CodeWikiBench",
        help="Directory that contains benchmark clones and result files.",
    )
    parser.add_argument(
        "--repos",
        default=None,
        help=(
            "Comma-separated repo keys. Defaults to the safe baseline run set for run/all, "
            "and the recommended clone set for prepare."
        ),
    )
    parser.add_argument("--yes-xl", action="store_true", help="Allow XL repositories.")
    parser.add_argument("--dry-run", action="store_true", help="Print work without running it.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="Show the repository manifest.")
    subparsers.add_parser("prepare", help="Clone selected repositories with --depth 1.")

    run_parser = subparsers.add_parser("run", help="Run cold/warm/small-delta scenarios.")
    add_run_options(run_parser)

    all_parser = subparsers.add_parser("all", help="Prepare repositories, then run benchmarks.")
    add_run_options(all_parser)
    return parser


def add_run_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--scenarios",
        default=",".join(DEFAULT_SCENARIOS),
        help="Comma-separated scenarios: cold,warm,small-delta.",
    )
    parser.add_argument(
        "--timeout-minutes",
        type=float,
        default=120.0,
        help="Per CLI command timeout.",
    )
    parser.add_argument(
        "--status-interval",
        type=float,
        default=DEFAULT_STATUS_INTERVAL_SECONDS,
        help="Seconds between progress heartbeats while analyze/update commands are still running.",
    )


def select_repos(repo_keys: str | None, *, mode: str, allow_xl: bool) -> list[BenchRepo]:
    if repo_keys:
        keys = [key.strip() for key in repo_keys.split(",") if key.strip()]
        unknown = sorted(set(keys) - set(REPOS_BY_KEY))
        if unknown:
            raise SystemExit(f"Unknown repository key(s): {', '.join(unknown)}")
        repos = [REPOS_BY_KEY[key] for key in keys]
    elif mode == "prepare":
        repos = [repo for repo in REPOS if repo.default_clone]
    else:
        repos = [repo for repo in REPOS if repo.default_run]

    xl_repos = [repo.key for repo in repos if repo.xl]
    if xl_repos and not allow_xl:
        raise SystemExit(
            "XL repositories are disabled by default. Re-run with --yes-xl for: "
            + ", ".join(xl_repos)
        )
    return repos


def list_repos() -> None:
    rows = [
        {
            "key": repo.key,
            "tier": repo.tier,
            "slug": repo.slug,
            "default_clone": repo.default_clone,
            "default_run": repo.default_run,
            "xl": repo.xl,
            "research": repo.research,
        }
        for repo in REPOS
    ]
    print(json.dumps(rows, indent=2, sort_keys=True))


def prepare_repos(root: Path, repos: Iterable[BenchRepo], *, dry_run: bool) -> None:
    repos = list(repos)
    progress = ProgressReporter(total_steps=len(repos), label="prepare")
    root.mkdir(parents=True, exist_ok=True)
    try:
        for repo in repos:
            target = root / repo.dirname
            if (target / ".git").exists():
                progress.skipped(f"existing clone {repo.slug} -> {target}")
                continue
            command = clone_command(repo, target)
            progress.start(f"clone {repo.slug}")
            if dry_run:
                progress.bar.write("dry-run: " + format_command(command))
                progress.done(f"clone {repo.slug}", elapsed_seconds=0.0, exit_code=0)
                continue
            result = run_streaming_command(command, cwd=root)
            progress.done(
                f"clone {repo.slug}",
                elapsed_seconds=result.elapsed_seconds,
                exit_code=result.exit_code,
            )
            if result.exit_code != 0:
                raise SystemExit(f"Clone failed for {repo.slug} with exit code {result.exit_code}.")
    finally:
        progress.close()


def run_benchmarks(
    root: Path,
    repos: Iterable[BenchRepo],
    *,
    scenarios: tuple[str, ...],
    timeout_minutes: float,
    status_interval_seconds: float,
    dry_run: bool,
) -> None:
    repos = list(repos)
    unsupported = sorted(set(scenarios) - set(DEFAULT_SCENARIOS))
    if unsupported:
        raise SystemExit(f"Unsupported scenario(s): {', '.join(unsupported)}")

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    result_dir = root / "results" / run_id
    if not dry_run:
        result_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = result_dir / "results.jsonl"
    csv_path = result_dir / "summary.csv"

    records: list[dict[str, Any]] = []
    progress = ProgressReporter(
        total_steps=sum(command_count_for_scenarios(scenarios) for _repo in repos),
        label="benchmark",
    )
    try:
        for repo in repos:
            repo_path = root / repo.dirname
            if not repo_path.exists():
                if dry_run:
                    progress.bar.write(
                        f"dry-run: repository is missing, would require prepare first: {repo_path}"
                    )
                else:
                    raise SystemExit(f"Repository is missing: {repo_path}. Run prepare first.")
            db_path = result_dir / f"{repo.key}.sqlite3"
            db_url = sqlite_url(db_path)
            repo_records = run_repo_scenarios(
                repo,
                repo_path,
                db_url=db_url,
                scenarios=scenarios,
                timeout_seconds=timeout_minutes * 60,
                status_interval_seconds=status_interval_seconds,
                dry_run=dry_run,
                progress=progress,
            )
            records.extend(repo_records)
            if not dry_run:
                append_jsonl(jsonl_path, repo_records)
    finally:
        progress.close()

    if dry_run:
        print(f"dry-run: would write benchmark results: {jsonl_path}")
        print(f"dry-run: would write benchmark summary: {csv_path}")
    else:
        write_summary_csv(csv_path, records)
        print(f"wrote benchmark results: {jsonl_path}")
        print(f"wrote benchmark summary: {csv_path}")


def run_repo_scenarios(
    repo: BenchRepo,
    repo_path: Path,
    *,
    db_url: str,
    scenarios: tuple[str, ...],
    timeout_seconds: float,
    status_interval_seconds: float,
    dry_run: bool,
    progress: ProgressReporter,
) -> list[dict[str, Any]]:
    progress.bar.write(f"benchmarking {repo.slug} ({repo.tier})")
    records: list[dict[str, Any]] = []

    if "cold" in scenarios:
        records.append(
            run_codewiki(
                repo,
                repo_path,
                db_url=db_url,
                scenario="repo-add",
                args=["repos", "add", str(repo_path), "--name", f"bench-{repo.key}", "--json"],
                timeout_seconds=timeout_seconds,
                status_interval_seconds=status_interval_seconds,
                dry_run=dry_run,
                progress=progress,
            )
        )
        records.append(
            run_codewiki(
                repo,
                repo_path,
                db_url=db_url,
                scenario="cold",
                args=[
                    "analyze",
                    str(repo_path),
                    "--force",
                    "--no-community-summaries",
                    "--progress",
                    "--json",
                ],
                timeout_seconds=timeout_seconds,
                status_interval_seconds=status_interval_seconds,
                dry_run=dry_run,
                progress=progress,
            )
        )

    if "warm" in scenarios:
        records.append(
            run_codewiki(
                repo,
                repo_path,
                db_url=db_url,
                scenario="warm",
                args=["analyze", str(repo_path), "--no-community-summaries", "--progress", "--json"],
                timeout_seconds=timeout_seconds,
                status_interval_seconds=status_interval_seconds,
                dry_run=dry_run,
                progress=progress,
            )
        )

    if "small-delta" in scenarios:
        records.append(
            run_small_delta(
                repo,
                repo_path,
                db_url=db_url,
                timeout_seconds=timeout_seconds,
                status_interval_seconds=status_interval_seconds,
                dry_run=dry_run,
                progress=progress,
            )
        )

    return records


def run_small_delta(
    repo: BenchRepo,
    repo_path: Path,
    *,
    db_url: str,
    timeout_seconds: float,
    status_interval_seconds: float,
    dry_run: bool,
    progress: ProgressReporter,
) -> dict[str, Any]:
    filename, content = DELTA_CONTENT.get(repo.language_hint, DELTA_CONTENT["ts"])
    delta_path = repo_path / filename
    if delta_path.exists():
        raise SystemExit(f"Refusing to overwrite existing delta file: {delta_path}")

    if dry_run:
        progress.bar.write(f"dry-run: write {delta_path}")
        return run_codewiki(
            repo,
            repo_path,
            db_url=db_url,
            scenario="small-delta",
            args=["update", str(repo_path), "--no-regenerate-wiki", "--json"],
            timeout_seconds=timeout_seconds,
            status_interval_seconds=status_interval_seconds,
            dry_run=True,
            progress=progress,
        )

    try:
        delta_path.write_text(content, encoding="utf-8")
        return run_codewiki(
            repo,
            repo_path,
            db_url=db_url,
            scenario="small-delta",
            args=["update", str(repo_path), "--no-regenerate-wiki", "--json"],
            timeout_seconds=timeout_seconds,
            status_interval_seconds=status_interval_seconds,
            dry_run=False,
            progress=progress,
        )
    finally:
        delta_path.unlink(missing_ok=True)


def run_codewiki(
    repo: BenchRepo,
    repo_path: Path,
    *,
    db_url: str,
    scenario: str,
    args: list[str],
    timeout_seconds: float,
    status_interval_seconds: float,
    dry_run: bool,
    progress: ProgressReporter,
) -> dict[str, Any]:
    command = [
        sys.executable,
        "-c",
        "from backend.app.cli.main import main; main()",
        "--database-url",
        db_url,
        *args,
    ]
    progress.start(f"{repo.key}:{scenario}")
    if dry_run:
        progress.bar.write("dry-run: " + format_command(command))
        result = CommandResult(command, 0.0, 0, "{}", "")
    else:
        db_path = sqlite_path_from_url(db_url)
        result = run_command(
            command,
            cwd=PROJECT_ROOT,
            timeout_seconds=timeout_seconds,
            status_interval_seconds=status_interval_seconds,
            on_status=lambda elapsed: progress.running(
                f"{repo.key}:{scenario}",
                elapsed_seconds=elapsed,
                database_stats=read_database_write_stats(db_path),
            ),
            on_stderr_line=lambda line: _handle_progress_line(progress, line),
        )
    progress.done(
        f"{repo.key}:{scenario}",
        elapsed_seconds=result.elapsed_seconds,
        exit_code=result.exit_code,
    )

    payload = parse_json_output(result.stdout)
    return {
        "repo_key": repo.key,
        "repo_slug": repo.slug,
        "tier": repo.tier,
        "repo_path": str(repo_path),
        "scenario": scenario,
        "elapsed_seconds": round(result.elapsed_seconds, 3),
        "exit_code": result.exit_code,
        "timed_out": result.timed_out,
        "db_url": db_url,
        "payload": payload,
        "stderr_tail": result.stderr[-4000:],
        "command": result.command,
    }


def run_command(
    command: list[str],
    *,
    cwd: Path,
    timeout_seconds: float | None,
    status_interval_seconds: float = DEFAULT_STATUS_INTERVAL_SECONDS,
    on_status: Callable[[float], None] | None = None,
    on_stderr_line: Callable[[str], bool] | None = None,
) -> CommandResult:
    started = time.perf_counter()
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    stdout_thread = threading.Thread(
        target=_read_stream,
        args=(process.stdout, stdout_chunks, None),
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=_read_stream,
        args=(process.stderr, stderr_chunks, sys.stderr, on_stderr_line),
        daemon=True,
    )
    stdout_thread.start()
    stderr_thread.start()
    next_status_at = max(status_interval_seconds, 0.0)
    while process.poll() is None:
        elapsed = time.perf_counter() - started
        if timeout_seconds is not None and elapsed >= timeout_seconds:
            process.kill()
            process.wait()
            stdout_thread.join(timeout=1)
            stderr_thread.join(timeout=1)
            elapsed = time.perf_counter() - started
            return CommandResult(
                command=command,
                elapsed_seconds=elapsed,
                exit_code=124,
                stdout="".join(stdout_chunks),
                stderr="".join(stderr_chunks),
                timed_out=True,
            )
        if on_status is not None and status_interval_seconds > 0 and elapsed >= next_status_at:
            on_status(elapsed)
            next_status_at += status_interval_seconds
        poll_interval = 0.5
        if status_interval_seconds > 0:
            poll_interval = min(poll_interval, max(status_interval_seconds / 2, 0.05))
        time.sleep(poll_interval)

    stdout_thread.join()
    stderr_thread.join()
    stdout = "".join(stdout_chunks)
    stderr = "".join(stderr_chunks)
    elapsed = time.perf_counter() - started
    if process.returncode != 0:
        print_error_block(command, stderr)
    return CommandResult(
        command=command,
        elapsed_seconds=elapsed,
        exit_code=process.returncode,
        stdout=stdout,
        stderr=stderr,
    )

def run_streaming_command(command: list[str], *, cwd: Path) -> CommandResult:
    started = time.perf_counter()
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=False,
        text=True,
    )
    elapsed = time.perf_counter() - started
    return CommandResult(
        command=command,
        elapsed_seconds=elapsed,
        exit_code=completed.returncode,
        stdout="",
        stderr="",
    )


def _read_stream(
    stream: Any,
    chunks: list[str],
    echo_stream: Any | None,
    line_callback: Callable[[str], bool] | None = None,
) -> None:
    if stream is None:
        return
    for line in stream:
        chunks.append(line)
        if line_callback is not None and line_callback(line):
            continue
        if echo_stream is not None:
            echo_stream.write(line)
            echo_stream.flush()


def _handle_progress_line(progress: ProgressReporter, line: str) -> bool:
    if not line.startswith("PROGRESS "):
        if progress.is_tty and line.strip():
            progress.message(line.rstrip())
            return True
        return False
    progress.analysis_progress(line)
    return sys.stderr.isatty()


def split_progress_message(message: str) -> tuple[str, str | None]:
    if " path=" in message:
        status, path = message.split(" path=", 1)
        return status, f"path={path}"
    if " repo=" in message and " path=" in message:
        status, rest = message.split(" repo=", 1)
        return status, f"repo={rest}"
    if " nodes=" in message:
        status, rest = message.split(" nodes=", 1)
        return status, f"nodes={rest}"
    if " scanned=" in message:
        status, rest = message.split(" scanned=", 1)
        return status, f"scanned={rest}"
    if " total=" in message:
        status, rest = message.split(" total=", 1)
        return status, f"total={rest}"
    if " parsed_files=" in message:
        status, rest = message.split(" parsed_files=", 1)
        return status, f"parsed_files={rest}"
    if " mode=" in message:
        status, rest = message.split(" mode=", 1)
        return status, f"mode={rest}"
    return message, None


def print_error_block(command: list[str], stderr: str) -> None:
    print("", file=sys.stderr)
    print("=" * 80, file=sys.stderr)
    print("COMMAND FAILED", file=sys.stderr)
    print("Command:", format_command(command), file=sys.stderr)
    print("-" * 80, file=sys.stderr)
    print((stderr or "").strip()[-4000:], file=sys.stderr)
    print("=" * 80, file=sys.stderr)


def parse_json_output(output: str) -> dict[str, Any]:
    output = output.strip()
    if not output:
        return {}
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        return {"raw_stdout_tail": output[-4000:]}
    return payload if isinstance(payload, dict) else {"value": payload}


def read_database_write_stats(path: Path) -> DatabaseWriteStats:
    if not path.exists():
        return DatabaseWriteStats(total_rows=0, table_counts={})

    try:
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=0.2)
    except sqlite3.Error as error:
        return DatabaseWriteStats(total_rows=0, table_counts={}, error=str(error))

    try:
        connection.execute("PRAGMA query_only = TRUE")
        table_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'virtual table')"
            )
        }
        counts: dict[str, int] = {}
        for table_name, label in DATABASE_WRITE_TABLES:
            if table_name not in table_names:
                continue
            row = connection.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()
            counts[label] = int(row[0])
        return DatabaseWriteStats(total_rows=sum(counts.values()), table_counts=counts)
    except sqlite3.Error as error:
        return DatabaseWriteStats(total_rows=0, table_counts={}, error=str(error))
    finally:
        connection.close()


def format_database_write_stats(stats: DatabaseWriteStats) -> str:
    if stats.error is not None:
        return f"db rows unavailable ({stats.error})"
    if not stats.table_counts:
        return "db rows 0"

    detail_labels = ("nodes", "edges", "chunks", "communities", "embeddings", "pages")
    details = [
        f"{label}={stats.table_counts[label]:,}"
        for label in detail_labels
        if stats.table_counts.get(label)
    ]
    if details:
        return f"db rows {stats.total_rows:,} ({', '.join(details)})"
    return f"db rows {stats.total_rows:,}"


def format_command(command: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in command)


def append_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> None:
    with path.open("a", encoding="utf-8") as file:
        for record in records:
            file.write(json.dumps(record, sort_keys=True) + "\n")


def write_summary_csv(path: Path, records: list[dict[str, Any]]) -> None:
    fields = [
        "repo_key",
        "tier",
        "scenario",
        "elapsed_seconds",
        "exit_code",
        "timed_out",
        "mode",
        "scanned_count",
        "parsed_file_count",
        "reused_file_count",
        "node_count",
        "edge_count",
        "community_count",
        "chunk_count",
        "error_count",
    ]
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for record in records:
            payload = record.get("payload") or {}
            row = {
                "repo_key": record["repo_key"],
                "tier": record["tier"],
                "scenario": record["scenario"],
                "elapsed_seconds": record["elapsed_seconds"],
                "exit_code": record["exit_code"],
                "timed_out": record["timed_out"],
                "mode": payload.get("mode"),
                "scanned_count": payload.get("scanned_count"),
                "parsed_file_count": payload.get("parsed_file_count"),
                "reused_file_count": payload.get("reused_file_count"),
                "node_count": payload.get("node_count"),
                "edge_count": payload.get("edge_count"),
                "community_count": payload.get("community_count"),
                "chunk_count": payload.get("chunk_count"),
                "error_count": len(payload.get("errors") or []),
            }
            writer.writerow(row)


def sqlite_url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path.as_posix()}"


def sqlite_path_from_url(url: str) -> Path:
    for prefix in ("sqlite+aiosqlite:///", "sqlite:///"):
        if url.startswith(prefix):
            return Path(url.removeprefix(prefix))
    raise ValueError(f"Only sqlite database URLs are supported: {url}")


def clone_command(repo: BenchRepo, target: Path) -> list[str]:
    return ["git", *GIT_CLONE_ARGS, repo.url, str(target)]


def command_count_for_scenarios(scenarios: tuple[str, ...]) -> int:
    count = 0
    if "cold" in scenarios:
        count += 2
    if "warm" in scenarios:
        count += 1
    if "small-delta" in scenarios:
        count += 1
    return count


def format_duration(seconds: float) -> str:
    seconds = max(seconds, 0.0)
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, remaining_seconds = divmod(int(seconds), 60)
    hours, remaining_minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h{remaining_minutes:02d}m{remaining_seconds:02d}s"
    return f"{remaining_minutes}m{remaining_seconds:02d}s"


def repo_manifest() -> list[dict[str, Any]]:
    return [asdict(repo) for repo in REPOS]


if __name__ == "__main__":
    raise SystemExit(main())
