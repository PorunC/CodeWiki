from __future__ import annotations

import importlib.metadata
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel

from backend.app.database import CodeWikiStore
from backend.app.mcp_server.types import JsonObject
from backend.app.services.repo_scanner import RepoDescriptor, RepoScanner, is_git_url


def resolve_repo(store: CodeWikiStore, selector: str | None) -> RepoDescriptor:
    selector = (selector or ".").strip() or "."
    if repo := store.get_repo(selector):
        return repo

    repos = store.list_repos()
    exact_name_matches = [repo for repo in repos if repo.name == selector]
    if len(exact_name_matches) == 1:
        return exact_name_matches[0]
    if len(exact_name_matches) > 1:
        raise ValueError(f"Repository name is ambiguous: {selector}")

    prefix_matches = [repo for repo in repos if repo.id.startswith(selector)]
    if len(prefix_matches) == 1:
        return prefix_matches[0]
    if len(prefix_matches) > 1:
        raise ValueError(f"Repository id prefix is ambiguous: {selector}")

    path = Path(selector).expanduser()
    if path.exists() and path.is_dir():
        resolved_path = path.resolve()
        for repo in repos:
            if Path(repo.path).expanduser().resolve() == resolved_path:
                return repo
        return store.upsert_repo(RepoScanner().describe(str(resolved_path)))

    if is_git_url(selector):
        return store.upsert_repo(RepoScanner().describe(selector))

    raise ValueError(
        f"Repository not found: {selector}. Use a repo id, id prefix, name, path, Git URL, "
        "or run from inside a repository directory."
    )


def repo_payload(repo: RepoDescriptor) -> JsonObject:
    return jsonable(repo)


def object_schema(properties: JsonObject, *, required: list[str] | None = None) -> JsonObject:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


def jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return jsonable(asdict(cast(Any, value)))
    if isinstance(value, BaseModel):
        return jsonable(value.model_dump())
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def package_version() -> str:
    try:
        return importlib.metadata.version("codewiki")
    except importlib.metadata.PackageNotFoundError:
        return "0.1.0"
