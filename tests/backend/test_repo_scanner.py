import hashlib
from pathlib import Path

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


def test_scan_records_git_last_commit_time_for_source_files(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "main.py").write_text("print('hello')\n")
    (tmp_path / "notes.md").write_text("# Notes\n")
    timestamp = "2024-01-02T03:04:05+00:00"

    def fake_commit_times(root: Path, paths: list[str]) -> dict[str, str]:
        assert root == tmp_path
        assert paths == ["main.py"]
        return {"main.py": timestamp}

    monkeypatch.setattr(
        "backend.app.services.repo_scanner.scanner.git_file_commit_times",
        fake_commit_times,
    )

    result = RepoScanner().scan(str(tmp_path))
    files = {item.path: item for item in result.files}

    assert files["main.py"].last_commit_at == timestamp
    assert files["notes.md"].last_commit_at is None
