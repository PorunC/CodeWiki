from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.config import get_settings
from backend.app.db.store import get_store
from backend.app.main import create_app


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

    get_settings.cache_clear()
    get_store.cache_clear()


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
