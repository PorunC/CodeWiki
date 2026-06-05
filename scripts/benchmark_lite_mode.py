"""Synthetic Lite Mode stress runner.

The full repository benchmark runner targets real open-source repositories and the
full analyze/update workflow. This runner focuses on CodeWiki Lite Mode's
agent-facing path: project-local indexing, query/context/trace/node/files, affected
analysis, status freshness, and incremental sync.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shlex
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class LiteCommandResult:
    scenario: str
    command: list[str]
    elapsed_seconds: float
    exit_code: int
    payload: dict[str, Any]
    stderr_tail: str


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a synthetic CodeWiki Lite Mode stress test.")
    parser.add_argument("--root", default="~/CodeWikiLiteBench", help="Benchmark output root.")
    parser.add_argument("--files", type=int, default=600, help="Number of Python modules to generate.")
    parser.add_argument("--fanout", type=int, default=3, help="Calls each generated function makes.")
    parser.add_argument("--timeout-seconds", type=float, default=300.0, help="Per-command timeout.")
    parser.add_argument("--keep-repo", action="store_true", help="Keep generated source repository.")
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    result_dir = root / "results" / run_id
    repo_dir = root / "repos" / f"synthetic-py-{args.files}"
    result_dir.mkdir(parents=True, exist_ok=True)
    repo_dir.parent.mkdir(parents=True, exist_ok=True)

    if repo_dir.exists():
        shutil.rmtree(repo_dir)
    generate_python_repo(repo_dir, files=args.files, fanout=args.fanout)

    records: list[LiteCommandResult] = []
    try:
        records.append(run_lite("cold-index", ["lite", "index", str(repo_dir), "--json"], args.timeout_seconds))
        records.append(run_lite("warm-status", ["lite", "status", str(repo_dir), "--json"], args.timeout_seconds))
        records.append(run_lite("query", ["lite", "query", "func_10", str(repo_dir), "--json"], args.timeout_seconds))
        records.append(
            run_lite(
                "context",
                ["lite", "context", "func_10 helper call graph", str(repo_dir), "--json"],
                args.timeout_seconds,
            )
        )
        records.append(run_lite("trace", ["lite", "trace", "func_20", "func_10", str(repo_dir), "--json"], args.timeout_seconds))
        records.append(run_lite("node", ["lite", "node", "func_10", str(repo_dir), "--json"], args.timeout_seconds))
        records.append(run_lite("files-index", ["lite", "files", str(repo_dir), "--json"], args.timeout_seconds))

        delta_file = repo_dir / "pkg" / "module_0000.py"
        delta_file.write_text(delta_file.read_text(encoding="utf-8") + "\nDELTA_VALUE = 1\n", encoding="utf-8")
        records.append(
            run_lite(
                "affected",
                ["lite", "affected", "pkg/module_0000.py", "--path", str(repo_dir), "--json"],
                args.timeout_seconds,
            )
        )
        records.append(run_lite("stale-status", ["lite", "status", str(repo_dir), "--json"], args.timeout_seconds))
        records.append(run_lite("sync", ["lite", "sync", str(repo_dir), "--json"], args.timeout_seconds))
        records.append(run_lite("fresh-status", ["lite", "status", str(repo_dir), "--json"], args.timeout_seconds))
    finally:
        if not args.keep_repo:
            shutil.rmtree(repo_dir, ignore_errors=True)

    jsonl_path = result_dir / "lite-results.jsonl"
    csv_path = result_dir / "lite-summary.csv"
    write_jsonl(jsonl_path, records)
    write_summary(csv_path, records, files=args.files, fanout=args.fanout)
    print(f"wrote lite benchmark results: {jsonl_path}")
    print(f"wrote lite benchmark summary: {csv_path}")
    return 0 if all(record.exit_code == 0 for record in records) else 1


def generate_python_repo(root: Path, *, files: int, fanout: int) -> None:
    package = root / "pkg"
    tests = root / "tests"
    package.mkdir(parents=True)
    tests.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    for index in range(files):
        imports = []
        calls = []
        for offset in range(1, fanout + 1):
            target = (index + offset) % files
            imports.append(f"from pkg.module_{target:04d} import func_{target}")
            calls.append(f"    total += func_{target}(value - {offset})")
        body = [
            *imports,
            "",
            f"def func_{index}(value):",
            f"    total = value + {index}",
            *calls,
            "    return total",
            "",
        ]
        (package / f"module_{index:04d}.py").write_text("\n".join(body), encoding="utf-8")
    (tests / "test_smoke.py").write_text(
        "from pkg.module_0000 import func_0\n\n\ndef test_smoke():\n    assert func_0(1) > 0\n",
        encoding="utf-8",
    )
    (root / "README.md").write_text(f"# Synthetic Lite Bench\n\nFiles: {files}\n", encoding="utf-8")


def run_lite(scenario: str, args: list[str], timeout_seconds: float) -> LiteCommandResult:
    command = codewiki_command(args)
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
        check=False,
    )
    elapsed = time.perf_counter() - started
    payload = parse_json_output(completed.stdout)
    print(f"{scenario}: exit={completed.returncode} elapsed={elapsed:.3f}s")
    return LiteCommandResult(
        scenario=scenario,
        command=command,
        elapsed_seconds=round(elapsed, 3),
        exit_code=completed.returncode,
        payload=payload,
        stderr_tail=completed.stderr[-4000:],
    )


def codewiki_command(args: list[str]) -> list[str]:
    override = os.environ.get("CODEWIKI_CLI")
    if override:
        return [*shlex.split(override), *args]
    return [
        os.environ.get("NPM", "npm"),
        "--prefix",
        str(PROJECT_ROOT / "backend"),
        "exec",
        "--",
        "tsx",
        "--",
        "src/cli.ts",
        *args,
    ]


def parse_json_output(output: str) -> dict[str, Any]:
    text = output.strip()
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {"raw_stdout_tail": text[-4000:]}
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, list):
        return {"result_count": len(payload), "first_result": payload[0] if payload else None}
    return {"value": payload}


def write_jsonl(path: Path, records: list[LiteCommandResult]) -> None:
    with path.open("w", encoding="utf-8") as file:
        for record in records:
            file.write(json.dumps(record.__dict__, sort_keys=True) + "\n")


def write_summary(path: Path, records: list[LiteCommandResult], *, files: int, fanout: int) -> None:
    fields = [
        "scenario",
        "elapsed_seconds",
        "exit_code",
        "files",
        "fanout",
        "node_count",
        "edge_count",
        "file_count",
        "pending_sync",
        "pending_files",
        "result_count",
    ]
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for record in records:
            payload = record.payload
            raw_stats = payload.get("stats")
            stats: dict[str, Any] = raw_stats if isinstance(raw_stats, dict) else {}
            writer.writerow(
                {
                    "scenario": record.scenario,
                    "elapsed_seconds": record.elapsed_seconds,
                    "exit_code": record.exit_code,
                    "files": files,
                    "fanout": fanout,
                    "node_count": payload.get("node_count") or stats.get("selected_node_count"),
                    "edge_count": payload.get("edge_count") or stats.get("selected_edge_count"),
                    "file_count": payload.get("file_count"),
                    "pending_sync": payload.get("pending_sync"),
                    "pending_files": len(payload.get("pending_files") or []),
                    "result_count": payload.get("result_count"),
                }
            )


if __name__ == "__main__":
    raise SystemExit(main())
