from typing import Any, TypedDict

import click

from backend.app.cli.common import echo_json, resolve_repo, run_click_errors, store_from_context
from backend.app.services.repo_scanner import RepoScanner
from backend.app.services.repo_scanner.tree import file_payload, file_tree_payload


class FilesPayload(TypedDict):
    repo_id: str
    root: dict[str, Any]
    files: list[dict[str, object]]
    scanned_count: int
    ignored_count: int
    skipped_count: int


def register(main: click.Group) -> None:
    @main.group("files")
    def files_group() -> None:
        """Inspect repository files and file trees."""

    @files_group.command("tree")
    @click.argument("repo", required=False)
    @click.option("--repo", "repo_option", help="Repository id, name, or path.")
    @click.option("--json", "as_json", is_flag=True, help="Print JSON output.")
    @click.pass_context
    def files_tree(
        ctx: click.Context,
        repo: str | None,
        repo_option: str | None,
        as_json: bool,
    ) -> None:
        """Show the scanned file tree for REPO."""
        payload = _files_payload(ctx, repo_option or repo)
        if as_json:
            echo_json(payload)
            return
        _print_tree(payload["root"])

    @files_group.command("list")
    @click.argument("repo", required=False)
    @click.option("--repo", "repo_option", help="Repository id, name, or path.")
    @click.option("--source-only", is_flag=True, help="Only show source files.")
    @click.option("--json", "as_json", is_flag=True, help="Print JSON output.")
    @click.pass_context
    def files_list(
        ctx: click.Context,
        repo: str | None,
        repo_option: str | None,
        source_only: bool,
        as_json: bool,
    ) -> None:
        """List scanned files for REPO."""
        payload = _files_payload(ctx, repo_option or repo)
        files = payload["files"]
        if source_only:
            files = [item for item in files if item["is_source"]]
            payload = {**payload, "files": files}
        if as_json:
            echo_json(payload)
            return
        for item in files:
            language = item["language"] or "text"
            click.echo(f"{item['path']}  {language}  {item['size_bytes']} bytes")


def _files_payload(ctx: click.Context, repo_selector: str | None) -> FilesPayload:
    store = store_from_context(ctx)
    selected_repo = run_click_errors(lambda: resolve_repo(store, repo_selector))
    scan = run_click_errors(
        lambda: RepoScanner().scan(
            selected_repo.path,
            name=selected_repo.name,
            source_type=selected_repo.source_type,
        )
    )
    return {
        "repo_id": selected_repo.id,
        "root": file_tree_payload(selected_repo, scan.files),
        "files": [file_payload(scanned_file) for scanned_file in scan.files],
        "scanned_count": scan.scanned_count,
        "ignored_count": scan.ignored_count,
        "skipped_count": scan.skipped_count,
    }


def _print_tree(node: object, prefix: str = "") -> None:
    if not isinstance(node, dict):
        return
    name = str(node.get("name", ""))
    click.echo(f"{prefix}{name}/" if node.get("type") == "directory" else f"{prefix}{name}")
    children = node.get("children")
    if not isinstance(children, list):
        return
    for child in children:
        _print_tree(child, prefix=f"{prefix}  ")
