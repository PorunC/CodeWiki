import hashlib
from pathlib import Path


HTTP_METHODS = {"get", "post", "put", "patch", "delete", "options", "head"}


def relative_path(path: Path, repo_root: Path | None) -> str:
    if repo_root is None:
        return path.name
    return path.resolve().relative_to(repo_root.resolve()).as_posix()


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()
