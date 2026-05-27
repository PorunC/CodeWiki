import asyncio
import sys
import time

import click

from backend.app.config import get_settings
from backend.app.database import CodeWikiStore
from backend.app.cli.common import echo_json, jsonable, resolve_repo, run_click_errors, store_from_context
from backend.app.services.analyzer import AnalysisService, _llm_configured
from backend.app.services.community.namer import CommunityNamer
from backend.app.services.community.naming import CommunityNamingResult
from backend.app.services.incremental import IncrementalUpdater
from backend.app.services.incremental.watcher import IncrementalUpdateWatcher, WatchIterationResult
from backend.app.services.llm.gateway import LLMGateway

def register(main: click.Group) -> None:
    @main.command("analyze")
    @click.argument("repo", required=False)
    @click.option("--community-summaries/--no-community-summaries", default=True, show_default=True)
    @click.option("--force", is_flag=True, help="Ignore the incremental fast path and rebuild the graph.")
    @click.option("--progress", is_flag=True, help="Print analysis progress to stderr.")
    @click.option("--json", "as_json", is_flag=True, help="Print JSON output.")
    @click.pass_context
    def analyze_repo(
        ctx: click.Context,
        repo: str | None,
        community_summaries: bool,
        force: bool,
        progress: bool,
        as_json: bool,
    ) -> None:
        """Run full AST graph analysis for REPO.

        REPO can be an id, id prefix, registered name, path, Git URL, or omitted for the
        current directory.
        """
        store = store_from_context(ctx)
        selected_repo = run_click_errors(lambda: resolve_repo(store, repo))
        progress_printer = AnalysisProgressPrinter(enabled=progress)
        analysis = run_click_errors(
            lambda: asyncio.run(
                AnalysisService(store=store).analyze_with_community_summaries(
                    selected_repo.id,
                    name_communities=community_summaries,
                    force=force,
                    progress_callback=progress_printer,
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
    @click.option("--community-summaries/--no-community-summaries", default=True, show_default=True)
    @click.option("--json", "as_json", is_flag=True, help="Print JSON output.")
    @click.pass_context
    def update_repo(
        ctx: click.Context,
        repo: str | None,
        refresh_chunks: bool,
        regenerate_wiki: bool,
        community_summaries: bool,
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
        if community_summaries:
            naming_result = run_click_errors(
                lambda: asyncio.run(_name_communities(store, selected_repo.id)),
                capture_stdout=as_json,
            )
            payload["community_naming"] = jsonable(naming_result)
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
                pages = wiki_regeneration.get("pages")
                regenerated_count = len(pages) if isinstance(pages, list) else 0
                click.echo(f"Regenerated wiki pages: {regenerated_count}")
        if community_summaries:
            click.echo(f"Community summaries: {payload['community_naming']['status']}")

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


class AnalysisProgressPrinter:
    def __init__(self, *, enabled: bool, interval_seconds: float = 2.0) -> None:
        self.enabled = enabled
        self.interval_seconds = interval_seconds
        self.last_parse_update_at = 0.0
        self.dynamic = sys.stderr.isatty()

    def __call__(self, stage: str, payload: dict[str, object]) -> None:
        if not self.enabled:
            return
        message = self._message(stage, payload)
        if message:
            self._write(message, final=stage == "analysis_done")

    def _write(self, message: str, *, final: bool = False) -> None:
        if not self.dynamic:
            click.echo(message, err=True)
            return
        sys.stderr.write(f"\r\033[K{message}")
        if final:
            sys.stderr.write("\n")
        sys.stderr.flush()

    def _message(self, stage: str, payload: dict[str, object]) -> str | None:
        if stage == "scan_start":
            return f"PROGRESS scan start repo={payload.get('repo')} path={payload.get('path')}"
        if stage == "scan_done":
            return (
                "PROGRESS scan done "
                f"scanned={payload.get('scanned')} ignored={payload.get('ignored')} "
                f"skipped={payload.get('skipped')}"
            )
        if stage == "plan_done":
            return (
                "PROGRESS plan done "
                f"changed={payload.get('changed')} new={payload.get('new')} "
                f"deleted={payload.get('deleted')} unchanged={payload.get('unchanged')}"
            )
        if stage == "parse_start":
            return (
                "PROGRESS parse start "
                f"total={payload.get('total')} reused_symbols={payload.get('reused_files')}"
            )
        if stage == "parse_progress":
            completed = _int_value(payload.get("completed"))
            total = _int_value(payload.get("total"))
            now = time.monotonic()
            if completed != total and now - self.last_parse_update_at < self.interval_seconds:
                return None
            self.last_parse_update_at = now
            percent = (completed / total * 100) if total else 100.0
            return (
                f"PROGRESS parse {completed}/{total} ({percent:.1f}%) "
                f"path={payload.get('path')}"
            )
        if stage == "parse_done":
            return (
                "PROGRESS parse done "
                f"parsed_files={payload.get('parsed_files')} symbols={payload.get('symbols')} "
                f"errors={payload.get('errors')}"
            )
        if stage == "graph_start":
            return f"PROGRESS graph start symbols={payload.get('symbols')}"
        if stage == "graph_done":
            return f"PROGRESS graph done nodes={payload.get('nodes')} edges={payload.get('edges')}"
        if stage == "communities_start":
            return (
                "PROGRESS communities start "
                f"nodes={payload.get('nodes')} edges={payload.get('edges')}"
            )
        if stage == "communities_done":
            return (
                "PROGRESS communities done "
                f"communities={payload.get('communities')} "
                f"community_edges={payload.get('community_edges')}"
            )
        if stage == "persist_start":
            return (
                "PROGRESS persist start "
                f"nodes={payload.get('nodes')} edges={payload.get('edges')} "
                f"communities={payload.get('communities')}"
            )
        if stage == "persist_done":
            return "PROGRESS persist done"
        if stage == "analysis_done":
            return (
                "PROGRESS analysis done "
                f"mode={payload.get('mode')} nodes={payload.get('nodes')} edges={payload.get('edges')}"
            )
        print(f"PROGRESS {stage} {payload}", file=sys.stderr)
        return None


def _int_value(value: object, default: int = 0) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


async def _name_communities(store: CodeWikiStore, repo_id: str) -> CommunityNamingResult:
    settings = get_settings()
    if not _llm_configured(settings):
        return CommunityNamingResult(
            repo_id=repo_id,
            status="skipped",
            renamed_count=0,
            community_count=len(store.list_graph_communities(repo_id)),
            errors=["LLM community naming skipped because no LLM endpoint or API key is configured."],
        )
    return await CommunityNamer(LLMGateway(settings), store=store).summarize_communities(repo_id)
