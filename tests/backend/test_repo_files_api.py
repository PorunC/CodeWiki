from pathlib import Path
import subprocess

from fastapi.testclient import TestClient

from backend.app.config import get_settings
from backend.app.db.store import get_store
from backend.app.main import create_app
from backend.app.services.repo_scanner.git import git_list_files
from backend.app.services.repo_scanner.git_ops import GitOperations


def test_repo_files_api_returns_flat_files_and_tree(tmp_path: Path, monkeypatch) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "README.md").write_text("# Repo\n")
    src_dir = repo_dir / "src"
    src_dir.mkdir()
    (src_dir / "main.py").write_text("def run():\n    return 42\n")

    monkeypatch.setenv(
        "CODEWIKI_DATABASE_URL",
        f"sqlite+aiosqlite:///{tmp_path / 'codewiki.sqlite3'}",
    )
    get_settings.cache_clear()
    get_store.cache_clear()

    client = TestClient(create_app())
    repo_response = client.post("/api/repos", json={"path": str(repo_dir), "name": "repo"})
    repo_response.raise_for_status()
    repo_id = repo_response.json()["id"]

    response = client.get(f"/api/repos/{repo_id}/files")
    response.raise_for_status()
    data = response.json()

    assert data["repo_id"] == repo_id
    assert {file["path"] for file in data["files"]} == {"README.md", "src/main.py"}
    assert data["root"]["name"] == "repo"
    src_node = next(child for child in data["root"]["children"] if child["name"] == "src")
    assert src_node["type"] == "directory"
    assert src_node["children"][0]["path"] == "src/main.py"
    assert all("sha256" not in file for file in data["files"])

    get_settings.cache_clear()
    get_store.cache_clear()


def test_repo_files_api_uses_lightweight_scan(tmp_path: Path, monkeypatch) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "main.py").write_text("print('ok')\n")

    monkeypatch.setenv(
        "CODEWIKI_DATABASE_URL",
        f"sqlite+aiosqlite:///{tmp_path / 'codewiki.sqlite3'}",
    )
    get_settings.cache_clear()
    get_store.cache_clear()

    def fail_hash(_path: Path) -> str:
        raise AssertionError("/files should not hash file contents")

    def fail_commit_times(self, repo_path: Path, file_paths: list[str]) -> dict[str, str]:
        raise AssertionError("/files should not query per-file git commit times")

    monkeypatch.setattr("backend.app.services.repo_scanner.file_info.sha256_file", fail_hash)
    monkeypatch.setattr(GitOperations, "file_commit_times", fail_commit_times)

    client = TestClient(create_app())
    repo_response = client.post("/api/repos", json={"path": str(repo_dir), "name": "repo"})
    repo_response.raise_for_status()
    repo_id = repo_response.json()["id"]

    response = client.get(f"/api/repos/{repo_id}/files")
    response.raise_for_status()
    data = response.json()

    assert [file["path"] for file in data["files"]] == ["main.py"]

    get_settings.cache_clear()
    get_store.cache_clear()


def test_git_list_files_includes_tracked_and_untracked_files(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / ".gitignore").write_text("ignored.txt\n")
    (repo_dir / "tracked.py").write_text("print('tracked')\n")
    (repo_dir / "untracked.py").write_text("print('untracked')\n")
    (repo_dir / "ignored.txt").write_text("ignore me\n")

    subprocess.run(["git", "init"], cwd=repo_dir, check=True, stdout=subprocess.PIPE)
    subprocess.run(["git", "add", ".gitignore", "tracked.py"], cwd=repo_dir, check=True)

    assert git_list_files(repo_dir) == [".gitignore", "tracked.py", "untracked.py"]


def test_delete_repo_api_removes_repository(tmp_path: Path, monkeypatch) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "README.md").write_text("# Repo\n")

    monkeypatch.setenv(
        "CODEWIKI_DATABASE_URL",
        f"sqlite+aiosqlite:///{tmp_path / 'codewiki.sqlite3'}",
    )
    get_settings.cache_clear()
    get_store.cache_clear()

    client = TestClient(create_app())
    repo_response = client.post("/api/repos", json={"path": str(repo_dir), "name": "repo"})
    repo_response.raise_for_status()
    repo_id = repo_response.json()["id"]

    delete_response = client.delete(f"/api/repos/{repo_id}")

    assert delete_response.status_code == 204
    assert client.get(f"/api/repos/{repo_id}").status_code == 404
    assert client.get("/api/repos").json() == []
    assert client.delete(f"/api/repos/{repo_id}").status_code == 404

    get_settings.cache_clear()
    get_store.cache_clear()
