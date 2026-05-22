from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse


def now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


DatabaseBackend = Literal["sqlite", "postgresql"]


def database_backend_from_url(database_url: str) -> DatabaseBackend:
    scheme = urlparse(database_url).scheme
    if scheme in {"sqlite", "sqlite+aiosqlite"}:
        return "sqlite"
    if scheme in {"postgresql", "postgresql+psycopg"}:
        return "postgresql"
    raise ValueError(
        "Unsupported database URL scheme. Expected one of: "
        "sqlite://, sqlite+aiosqlite://, postgresql://, postgresql+psycopg://."
    )


def sync_database_url(database_url: str) -> str:
    backend = database_backend_from_url(database_url)
    if backend == "sqlite":
        return database_url.replace("sqlite+aiosqlite://", "sqlite://", 1)
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


def sqlite_path_from_url(database_url: str) -> Path:
    for prefix in ("sqlite+aiosqlite:///", "sqlite:///"):
        if database_url.startswith(prefix):
            return Path(database_url.removeprefix(prefix)).expanduser()
    raise ValueError(f"Only SQLite database URLs have local paths: {database_url}")
