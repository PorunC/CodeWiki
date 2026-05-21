import asyncio

import click

from backend.app.cli.common import echo_json, jsonable, resolve_repo, run_click_errors, store_from_context
from backend.app.services.analyzer import AnalysisService
from backend.app.services.incremental import IncrementalUpdater
from backend.app.services.incremental.watcher import IncrementalUpdateWatcher, WatchIterationResult

def register(main: click.Group) -> None:
    @main.command("analyze")
    @click.argument("repo", required=False)
    @click.option("--community-summaries/--no-community-summaries", default=False, show_default=True)
    @click.option("--force", is_flag=True, help="Ignore the incremental fast path and rebuild the graph.")
    @click.option("--json", "as_json", is_flag=True, help="Print JSON output.")
    @click.pass_context
    def analyze_repo(
        ctx: click.Context,
        repo: str | None,
        community_summaries: bool,
        force: bool,
        as_json: bool,
    ) -> None:
        """Run full AST graph analysis for REPO.

        REPO can be an id, id prefix, registered name, path, Git URL, or omitted for the
        current directory.
        """
        store = store_from_context(ctx)
        selected_repo = run_click_errors(lambda: resolve_repo(store, repo))
        analysis = run_click_errors(
            lambda: asyncio.run(
                AnalysisService(store=store).analyze_with_community_summaries(
                    selected_repo.id,
                    name_communities=community_summaries,
                    force=force,
                )
            ),
            capture_stdout=as_json,
        )
        result = analysis.analysis
        payload = {
            "run_id": result.run_id,
            "repo_id": result.repo_id,
            "status": result.status,
            "mode": result.mode,
            **result.stats(),
        }
        if analysis.community_naming is not None:
            payload["community_naming"] = jsonable(analysis.community_naming)
        if as_json:
            echo_json(payload)
            return
        click.echo(
            f"Analysis {result.status}: {result.node_count} nodes, "
            f"{result.edge_count} edges, {result.community_count} communities"
        )
        if analysis.community_naming is not None:
            click.echo(f"Community summaries: {analysis.community_naming.status}")
        click.echo(f"Run: {result.run_id}")

    @main.command("update")
    @click.argument("repo", required=False)
    @click.option("--refresh-chunks/--no-refresh-chunks", default=True, show_default=True)
    @click.option("--regenerate-wiki/--no-regenerate-wiki", default=True, show_default=True)
    @click.option("--json", "as_json", is_flag=True, help="Print JSON output.")
    @click.pass_context
    def update_repo(
        ctx: click.Context,
        repo: str | None,
        refresh_chunks: bool,
        regenerate_wiki: bool,
        as_json: bool,
    ) -> None:
        """Run incremental graph update for REPO."""
        store = store_from_context(ctx)
        selected_repo = run_click_errors(lambda: resolve_repo(store, repo))
        result, wiki_regeneration = run_click_errors(
            lambda: asyncio.run(
                IncrementalUpdater(store=store).update_with_wiki_regeneration(
                    selected_repo.id,
                    refresh_chunks=refresh_chunks,
                    regenerate_wiki=regenerate_wiki,
                )
            ),
            capture_stdout=as_json,
        )
        payload = {
            "run_id": result.run_id,
            "repo_id": result.repo_id,
            "status": result.status,
            **result.stats(),
            "wiki_regeneration": wiki_regeneration,
        }
        if as_json:
            echo_json(payload)
            return
        click.echo(
            f"Update {result.status}: {len(result.plan.affected_files)} affected files, "
            f"{result.node_count} nodes, {result.edge_count} edges"
        )
        if result.stale_pages:
            click.echo(f"Stale wiki pages: {', '.join(result.stale_pages)}")
            if wiki_regeneration.get("requested"):
                click.echo(f"Regenerated wiki pages: {len(wiki_regeneration.get('pages', []))}")

    @main.command("watch")
    @click.argument("repo", required=False)
    @click.option("--repo", "repo_option", help="Repository id, name, or path.")
    @click.option("--interval", default=2.0, show_default=True, type=float, help="Polling interval in seconds.")
    @click.option("--debounce", default=2.0, show_default=True, type=float, help="Quiet period before syncing.")
    @click.option("--refresh-chunks/--no-refresh-chunks", default=True, show_default=True)
    @click.pass_context
    def watch_repo(
        ctx: click.Context,
        repo: str | None,
        repo_option: str | None,
        interval: float,
        debounce: float,
        refresh_chunks: bool,
    ) -> None:
        """Watch a repository and run incremental graph/chunk updates."""
        store = store_from_context(ctx)
        selected_repo = run_click_errors(lambda: resolve_repo(store, repo_option or repo))
        click.echo(f"Watching {selected_repo.name} ({selected_repo.id}). Press Ctrl-C to stop.")

        def on_iteration(result: WatchIterationResult) -> None:
            if not result.changed:
                return
            click.echo(
                f"Updated {len(result.affected_files)} files: "
                f"{result.node_count} nodes, {result.edge_count} edges (run {result.run_id})"
            )

        try:
            IncrementalUpdateWatcher(store=store).run(
                selected_repo.id,
                interval_seconds=interval,
                debounce_seconds=debounce,
                refresh_chunks=refresh_chunks,
                on_iteration=on_iteration,
            )
        except KeyboardInterrupt:
            click.echo("Stopped watching.")
