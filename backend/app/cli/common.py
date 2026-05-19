import contextlib
import io
import json
import logging
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Callable, TypeVar

import click

from backend.app.database import SQLiteStore, get_store
from backend.app.services.repo_scanner import RepoDescriptor, RepoScanResult, RepoScanner, is_git_url

T = TypeVar("T")


def store_from_context(ctx: click.Context) -> SQLiteStore:
    obj = ctx.ensure_object(dict)
    store = obj.get("store")
    if store is None:
        store = get_store()
        obj["store"] = store
    if not isinstance(store, SQLiteStore):
        raise click.ClickException("CLI store is not initialized.")
    return store


def resolve_repo(
    store: SQLiteStore,
    selector: str | None,
    *,
    auto_register_paths: bool = True,
) -> RepoDescriptor:
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
        path_matches = [
            repo
            for repo in repos
            if Path(repo.path).expanduser().resolve() == resolved_path
        ]
        if path_matches:
            return path_matches[0]
        if auto_register_paths:
            return store.upsert_repo(RepoScanner().describe(str(resolved_path)))

    if is_git_url(selector) and auto_register_paths:
        return store.upsert_repo(RepoScanner().describe(selector))

    raise ValueError(
        f"Repository not found: {selector}. Use a repo id, id prefix, name, path, Git URL, "
        "or run from inside a repository directory."
    )


def can_resolve_repo_selector(store: SQLiteStore, selector: str) -> bool:
    try:
        resolve_repo(store, selector, auto_register_paths=False)
    except ValueError:
        return False
    return True


def parse_ask_args(
    store: SQLiteStore,
    args: tuple[str, ...],
    repo_option: str | None,
) -> tuple[str | None, str]:
    if repo_option:
        return repo_option, " ".join(args).strip()
    if len(args) == 1:
        return None, args[0]

    possible_repo = args[0]
    if can_resolve_repo_selector(store, possible_repo):
        return possible_repo, " ".join(args[1:]).strip()
    return None, " ".join(args).strip()


def repo_payload(repo: RepoDescriptor) -> dict[str, object]:
    return jsonable(repo)


def scan_payload(scan: RepoScanResult) -> dict[str, object]:
    return jsonable(scan)


def page_result_payload(result: Any) -> dict[str, object]:
    return {
        "page": jsonable(result.page),
        "validation_errors": result.validation_errors,
    }


def graph_status_payload(repo_id: str, nodes: list[Any], edges: list[Any]) -> dict[str, object]:
    nodes_by_type: dict[str, int] = {}
    edges_by_type: dict[str, int] = {}
    languages: dict[str, int] = {}
    for node in nodes:
        nodes_by_type[node.type] = nodes_by_type.get(node.type, 0) + 1
        if node.language:
            languages[node.language] = languages.get(node.language, 0) + 1
    for edge in edges:
        edges_by_type[edge.type] = edges_by_type.get(edge.type, 0) + 1
    return {
        "repo_id": repo_id,
        "file_count": sum(1 for node in nodes if node.type in {"file", "config"}),
        "node_count": len(nodes),
        "edge_count": len(edges),
        "nodes_by_type": dict(sorted(nodes_by_type.items())),
        "edges_by_type": dict(sorted(edges_by_type.items())),
        "languages": dict(sorted(languages.items())),
    }


def jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return jsonable(asdict(value))
    if hasattr(value, "model_dump"):
        return jsonable(value.model_dump())
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def echo_json(payload: Any) -> None:
    click.echo(json.dumps(jsonable(payload), indent=2, sort_keys=True))


def echo_table(headers: list[str], rows: list[list[object]]) -> None:
    widths = [
        max(len(headers[index]), *(len(str(row[index])) for row in rows))
        for index in range(len(headers))
    ]
    click.echo("  ".join(header.ljust(widths[index]) for index, header in enumerate(headers)))
    click.echo("  ".join("-" * width for width in widths))
    for row in rows:
        click.echo("  ".join(str(value).ljust(widths[index]) for index, value in enumerate(row)))


def run_click_errors(callback: Callable[[], T], *, capture_stdout: bool = False) -> T:
    try:
        if not capture_stdout:
            return callback()
        previous_logging_disable = logging.root.manager.disable
        logging.disable(logging.CRITICAL)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                return callback()
        finally:
            logging.disable(previous_logging_disable)
    except (FileNotFoundError, NotADirectoryError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
