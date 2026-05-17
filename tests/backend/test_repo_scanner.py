import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest

from backend.app.services.repo_scanner import RepoScanner


def test_describe_repo_defaults_name_to_directory() -> None:
    descriptor = RepoScanner().describe(str(Path.cwd()))

    assert descriptor.name == Path.cwd().name
    assert descriptor.source_type == "local"


def test_scan_respects_gitignore_and_detects_language(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("ignored.py\nnode_modules/\n*.log\n!keep.log\n")
    (tmp_path / "main.py").write_text("print('hello')\n")
    (tmp_path / "ignored.py").write_text("print('ignored')\n")
    (tmp_path / "keep.log").write_text("keep\n")
    (tmp_path / "skip.log").write_text("skip\n")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "package.js").write_text("ignored()\n")

    result = RepoScanner().scan(str(tmp_path))
    files = {item.path: item for item in result.files}

    assert "main.py" in files
    assert "keep.log" in files
    assert "ignored.py" not in files
    assert "skip.log" not in files
    assert "node_modules/package.js" not in files
    assert files["main.py"].language == "python"
    assert files["main.py"].is_source is True
    assert files["main.py"].sha256 == hashlib.sha256((tmp_path / "main.py").read_bytes()).hexdigest()


def test_scan_respects_nested_gitignore(tmp_path: Path) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / ".gitignore").write_text("*.ts\n!keep.ts\n")
    (nested / "skip.ts").write_text("const skip = true;\n")
    (nested / "keep.ts").write_text("const keep = true;\n")

    result = RepoScanner().scan(str(tmp_path))
    paths = {item.path for item in result.files}

    assert "nested/keep.ts" in paths
    assert "nested/skip.ts" not in paths


def test_scan_records_git_last_commit_time_for_source_files(tmp_path: Path) -> None:
    (tmp_path / "main.py").write_text("print('hello')\n")
    (tmp_path / "notes.md").write_text("# Notes\n")
    timestamp = "2024-01-02T03:04:05+00:00"

    result = RepoScanner(git_operations=_FakeGitOperations(timestamp)).scan(str(tmp_path))
    files = {item.path: item for item in result.files}

    assert files["main.py"].last_commit_at == timestamp
    assert files["notes.md"].last_commit_at is None


def test_describe_git_url_clones_remote_repository(tmp_path: Path) -> None:
    if shutil.which("git") is None:
        pytest.skip("git executable is required for clone integration test")

    source_repo = tmp_path / "source-repo"
    source_repo.mkdir()
    _git(source_repo, "init")
    _git(source_repo, "config", "user.email", "test@example.com")
    _git(source_repo, "config", "user.name", "Test User")
    (source_repo / "README.md").write_text("# Source\n")
    _git(source_repo, "add", "README.md")
    _git(source_repo, "commit", "-m", "initial")
    commit_hash = _git_output(source_repo, "rev-parse", "HEAD")

    scanner = RepoScanner(storage_dir=tmp_path / "storage")
    descriptor = scanner.describe(source_repo.resolve().as_uri())

    clone_path = Path(descriptor.path)
    assert clone_path != source_repo.resolve()
    assert clone_path.is_dir()
    assert (clone_path / "README.md").read_text() == "# Source\n"
    assert descriptor.name == "source-repo"
    assert descriptor.source_type == "git"
    assert descriptor.git_url == source_repo.resolve().as_uri()
    assert descriptor.commit_hash == commit_hash

    scan = scanner.scan(source_repo.resolve().as_uri())
    assert scan.repo.id == descriptor.id
    assert {file.path for file in scan.files} == {"README.md"}


def _git(repo_dir: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo_dir), *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _git_output(repo_dir: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo_dir), *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ).stdout.strip()


class _FakeGitOperations:
    def __init__(self, timestamp: str) -> None:
        self.timestamp = timestamp

    def metadata(self, repo_path: Path) -> tuple[str | None, str | None]:
        return None, None

    def file_commit_times(self, repo_path: Path, file_paths: list[str]) -> dict[str, str]:
        assert file_paths == ["main.py"]
        return {"main.py": self.timestamp}

    def clone(self, git_url: str, destination: Path) -> Path:
        raise AssertionError("clone should not be used for local scan")
