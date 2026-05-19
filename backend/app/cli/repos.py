import click

from backend.app.cli.common import (
    echo_json,
    echo_table,
    repo_payload,
    run_click_errors,
    scan_payload,
    store_from_context,
)
from backend.app.services.repo_scanner import RepoScanner


def register(main: click.Group) -> None:
    @main.group("repos")
    def repos_group() -> None:
        """Register and inspect repositories."""

    @repos_group.command("add")
    @click.argument("path", type=str)
    @click.option("--name", help="Repository display name.")
    @click.option("--source-type", default="local", show_default=True)
    @click.option("--json", "as_json", is_flag=True, help="Print JSON output.")
    @click.pass_context
    def add_repo(
        ctx: click.Context,
        path: str,
        name: str | None,
        source_type: str,
        as_json: bool,
    ) -> None:
        """Register PATH or Git URL in the local Code Wiki database."""
        store = store_from_context(ctx)
        repo = run_click_errors(lambda: RepoScanner().describe(path, name=name, source_type=source_type))
        repo = store.upsert_repo(repo)
        if as_json:
            echo_json(repo_payload(repo))
            return
        click.echo(f"Registered {repo.name} ({repo.id})")
        click.echo(repo.path)

    @repos_group.command("list")
    @click.option("--json", "as_json", is_flag=True, help="Print JSON output.")
    @click.pass_context
    def list_repos(ctx: click.Context, as_json: bool) -> None:
        """List registered repositories."""
        repos = store_from_context(ctx).list_repos()
        if as_json:
            echo_json([repo_payload(repo) for repo in repos])
            return
        if not repos:
            click.echo("No repositories registered.")
            return
        echo_table(
            ["id", "name", "source", "path"],
            [[repo.id, repo.name, repo.source_type, repo.path] for repo in repos],
        )

    @repos_group.command("scan")
    @click.argument("path", type=str)
    @click.option("--name", help="Repository display name.")
    @click.option("--source-type", default="local", show_default=True)
    @click.option("--json", "as_json", is_flag=True, help="Print JSON output.")
    def scan_repo(path: str, name: str | None, source_type: str, as_json: bool) -> None:
        """Scan PATH or Git URL without registering it."""
        scan = run_click_errors(lambda: RepoScanner().scan(path, name=name, source_type=source_type))
        if as_json:
            echo_json(scan_payload(scan))
            return
        click.echo(f"Repo: {scan.repo.name} ({scan.repo.id})")
        click.echo(f"Scanned: {scan.scanned_count}")
        click.echo(f"Ignored: {scan.ignored_count}")
        click.echo(f"Skipped: {scan.skipped_count}")
