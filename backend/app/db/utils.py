from datetime import UTC, datetime
from pathlib import Path


def now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def sqlite_path_from_url(database_url: str) -> Path:
    for prefix in ("sqlite+aiosqlite:///", "sqlite:///"):
        if database_url.startswith(prefix):
            return Path(database_url.removeprefix(prefix)).expanduser()
    raise ValueError(f"Only sqlite database URLs are supported: {database_url}")

