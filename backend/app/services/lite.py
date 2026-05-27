from __future__ import annotations

from pathlib import Path

from backend.app.database import CodeWikiStore, create_store
from backend.app.services.repo_scanner import RepoDescriptor, RepoScanner

LITE_DIR_NAME = ".codewiki"
LITE_DB_NAME = "codewiki-lite.sqlite3"


def lite_root(path: str | Path | None = None) -> Path:
    return Path(path or ".").expanduser().resolve()


def lite_dir(path: str | Path | None = None) -> Path:
    return lite_root(path) / LITE_DIR_NAME


def lite_database_path(path: str | Path | None = None) -> Path:
    return lite_dir(path) / LITE_DB_NAME


def lite_database_url(path: str | Path | None = None) -> str:
    return f"sqlite+aiosqlite:///{lite_database_path(path)}"


def create_lite_store(path: str | Path | None = None) -> CodeWikiStore:
    return create_store(lite_database_url(path))


def init_lite_repo(
    *,
    path: str | Path | None = None,
    name: str | None = None,
    source_type: str = "local",
) -> tuple[CodeWikiStore, RepoDescriptor, Path]:
    root = lite_root(path)
    root.mkdir(parents=True, exist_ok=True)
    lite_dir(root).mkdir(parents=True, exist_ok=True)
    store = create_lite_store(root)
    repo = store.upsert_repo(RepoScanner().describe(str(root), name=name, source_type=source_type))
    return store, repo, lite_database_path(root)
