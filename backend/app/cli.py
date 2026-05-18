import asyncio
import contextlib
import io
import json
import logging
import os
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

import click

from backend.app.config import get_settings
from backend.app.database import SQLiteStore, get_store
from backend.app.env_config import (
    LLM_PROFILES,
    codewiki_values,
    ensure_env_file,
    llm_profile_key,
    mask_config_values,
    parse_env_assignment,
    read_env_values,
    validate_env_key,
    write_env_values,
)
from backend.app.schemas.ask import AskRequest
from backend.app.services.analyzer import AnalysisService
from backend.app.services.graphrag import GraphRAGRetriever
from backend.app.services.graph.query import GraphQueryService
from backend.app.services.incremental import IncrementalUpdater
from backend.app.services.incremental.watcher import IncrementalUpdateWatcher, WatchIterationResult
from backend.app.services.llm_gateway import LLMGateway
from backend.app.services.question_answerer import QuestionAnswerer
from backend.app.services.repo_scanner import RepoDescriptor, RepoScanResult, RepoScanner, is_git_url
from backend.app.services.wiki import WikiGenerator


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.option(
    "--database-url",
    envvar="CODEWIKI_DATABASE_URL",
    help="SQLite database URL. Defaults to CODEWIKI_DATABASE_URL or app settings.",
)
@click.pass_context
def main(ctx: click.Context, database_url: str | None) -> None:
    """Code Wiki command line tools."""
    if database_url:
        os.environ["CODEWIKI_DATABASE_URL"] = database_url
        get_settings.cache_clear()
        get_store.cache_clear()
    ctx.obj = {"store": None}


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
    store = _store(ctx)
    repo = _run_click_errors(lambda: RepoScanner().describe(path, name=name, source_type=source_type))
    repo = store.upsert_repo(repo)
    if as_json:
        _echo_json(_repo_payload(repo))
        return
    click.echo(f"Registered {repo.name} ({repo.id})")
    click.echo(repo.path)


@repos_group.command("list")
@click.option("--json", "as_json", is_flag=True, help="Print JSON output.")
@click.pass_context
def list_repos(ctx: click.Context, as_json: bool) -> None:
    """List registered repositories."""
    repos = _store(ctx).list_repos()
    if as_json:
        _echo_json([_repo_payload(repo) for repo in repos])
        return
    if not repos:
        click.echo("No repositories registered.")
        return
    _echo_table(
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
    scan = _run_click_errors(lambda: RepoScanner().scan(path, name=name, source_type=source_type))
    if as_json:
        _echo_json(_scan_payload(scan))
        return
    click.echo(f"Repo: {scan.repo.name} ({scan.repo.id})")
    click.echo(f"Scanned: {scan.scanned_count}")
    click.echo(f"Ignored: {scan.ignored_count}")
    click.echo(f"Skipped: {scan.skipped_count}")


@main.command("config")
@click.option(
    "--env-file",
    type=click.Path(dir_okay=False, path_type=Path),
    default=Path(".env"),
    show_default=True,
    help="Environment file to read or update.",
)
@click.option("--init", "initialize", is_flag=True, help="Create the env file from .env.example.")
@click.option("--path", "show_path", is_flag=True, help="Print the resolved env file path.")
@click.option("--list", "list_values", is_flag=True, help="List configured CODEWIKI_* values.")
@click.option("--get", "get_keys", multiple=True, metavar="KEY", help="Print one env variable.")
@click.option("--set", "assignment_values", multiple=True, metavar="KEY=VALUE", help="Set an env variable.")
@click.option(
    "--profile",
    type=click.Choice(LLM_PROFILES),
    default="default",
    show_default=True,
    help="LLM profile used by --model, --provider-type, --endpoint, and --api-key.",
)
@click.option("--model", help="Set the selected LLM profile model.")
@click.option("--provider-type", help="Set the selected LLM profile provider type.")
@click.option("--endpoint", help="Set the selected LLM profile endpoint.")
@click.option("--api-key", help="Set the selected LLM profile API key.")
@click.option("--base-language", help="Set CODEWIKI_WIKI_BASE_LANGUAGE.")
@click.option("--translation-languages", help="Set CODEWIKI_WIKI_TRANSLATION_LANGUAGES.")
@click.option("--show-secrets", is_flag=True, help="Do not mask secret values in command output.")
@click.option("--json", "as_json", is_flag=True, help="Print JSON output.")
def configure_env(
    env_file: Path,
    initialize: bool,
    show_path: bool,
    list_values: bool,
    get_keys: tuple[str, ...],
    assignment_values: tuple[str, ...],
    profile: str,
    model: str | None,
    provider_type: str | None,
    endpoint: str | None,
    api_key: str | None,
    base_language: str | None,
    translation_languages: str | None,
    show_secrets: bool,
    as_json: bool,
) -> None:
    """Configure CodeWiki environment variables in an env file."""
    env_file = env_file.expanduser().resolve()
    example_file = Path(__file__).resolve().parents[2] / ".env.example"
    updates = _config_updates(
        assignment_values=assignment_values,
        profile=profile,
        model=model,
        provider_type=provider_type,
        endpoint=endpoint,
        api_key=api_key,
        base_language=base_language,
        translation_languages=translation_languages,
    )
    has_read_action = show_path or list_values or bool(get_keys)
    has_write_action = initialize or bool(updates)

    if not has_read_action and not has_write_action:
        created = ensure_env_file(env_file, example_file)
        values = read_env_values(env_file)
        updates = _prompt_config_values(values)
        write_env_values(env_file, updates)
        get_settings.cache_clear()
        get_store.cache_clear()
        _echo_config_update(env_file, created, updates, show_secrets=show_secrets, as_json=as_json)
        return

    created = ensure_env_file(env_file, example_file) if has_write_action else False
    if updates:
        write_env_values(env_file, updates)
        get_settings.cache_clear()
        get_store.cache_clear()

    values = read_env_values(env_file)
    if show_path and not (list_values or get_keys or updates or initialize):
        payload = {"env_file": str(env_file), "exists": env_file.exists()}
        _echo_json(payload) if as_json else click.echo(str(env_file))
        return

    if get_keys:
        selected = {validate_env_key(key): values.get(validate_env_key(key), "") for key in get_keys}
        _echo_config_values(selected, show_secrets=show_secrets, as_json=as_json)
        return

    if list_values:
        selected = codewiki_values(values)
        _echo_config_values(selected, show_secrets=show_secrets, as_json=as_json, env_file=env_file)
        return

    _echo_config_update(env_file, created, updates, show_secrets=show_secrets, as_json=as_json)


@main.command("analyze")
@click.argument("repo", required=False)
@click.option("--community-summaries/--no-community-summaries", default=True, show_default=True)
@click.option("--json", "as_json", is_flag=True, help="Print JSON output.")
@click.pass_context
def analyze_repo(
    ctx: click.Context,
    repo: str | None,
    community_summaries: bool,
    as_json: bool,
) -> None:
    """Run full AST graph analysis for REPO.

    REPO can be an id, id prefix, registered name, path, Git URL, or omitted for the
    current directory.
    """
    store = _store(ctx)
    selected_repo = _run_click_errors(lambda: _resolve_repo(store, repo))
    analysis = _run_click_errors(
        lambda: asyncio.run(
            AnalysisService(store=store).analyze_with_community_summaries(
                selected_repo.id,
                name_communities=community_summaries,
            )
        ),
        capture_stdout=as_json,
    )
    result = analysis.analysis
    payload = {
        "run_id": result.run_id,
        "repo_id": result.repo_id,
        "status": result.status,
        **result.stats(),
    }
    if analysis.community_naming is not None:
        payload["community_naming"] = _jsonable(analysis.community_naming)
    if as_json:
        _echo_json(payload)
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
    store = _store(ctx)
    selected_repo = _run_click_errors(lambda: _resolve_repo(store, repo))
    result, wiki_regeneration = _run_click_errors(
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
        _echo_json(payload)
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
    store = _store(ctx)
    selected_repo = _run_click_errors(lambda: _resolve_repo(store, repo_option or repo))
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


@main.group("graphrag")
def graphrag_group() -> None:
    """Build and retrieve GraphRAG context."""


@graphrag_group.command("build")
@click.argument("repo", required=False)
@click.option("--embeddings/--no-embeddings", default=False, show_default=True)
@click.option("--json", "as_json", is_flag=True, help="Print JSON output.")
@click.pass_context
def build_graphrag(ctx: click.Context, repo: str | None, embeddings: bool, as_json: bool) -> None:
    """Build source chunks and optional embeddings for REPO."""
    store = _store(ctx)
    selected_repo = _run_click_errors(lambda: _resolve_repo(store, repo))
    result = _run_click_errors(
        lambda: asyncio.run(
            GraphRAGRetriever(store=store).build_index(
                selected_repo.id,
                include_embeddings=embeddings,
            )
        ),
        capture_stdout=as_json,
    )
    payload = _jsonable(result)
    if as_json:
        _echo_json(payload)
        return
    click.echo(f"GraphRAG {result.status}: {result.chunk_count} chunks")
    if result.embedding_count:
        click.echo(f"Embeddings: {result.embedding_count} ({result.embedding_model})")


@main.group("graph")
def graph_group() -> None:
    """Query the analyzed code graph."""


@graph_group.command("search")
@click.argument("query", required=False, default="")
@click.argument("repo", required=False)
@click.option("--repo", "repo_option", help="Repository id, name, or path.")
@click.option("--type", "node_type", help="Filter by graph node type.")
@click.option("--language", help="Filter by language.")
@click.option("--path", "path_filter", help="Filter by file path substring.")
@click.option("--name", "name_filter", help="Filter by node name substring.")
@click.option("--limit", default=20, show_default=True, type=int)
@click.option("--json", "as_json", is_flag=True, help="Print JSON output.")
@click.pass_context
def graph_search(
    ctx: click.Context,
    query: str,
    repo: str | None,
    repo_option: str | None,
    node_type: str | None,
    language: str | None,
    path_filter: str | None,
    name_filter: str | None,
    limit: int,
    as_json: bool,
) -> None:
    """Search graph symbols by name, path, signature, or docstring."""
    store = _store(ctx)
    selected_repo = _run_click_errors(lambda: _resolve_repo(store, repo_option or repo))
    hits = _run_click_errors(
        lambda: GraphQueryService(store=store).search(
            selected_repo.id,
            query,
            types=[node_type] if node_type else None,
            languages=[language] if language else None,
            path_filters=[path_filter] if path_filter else None,
            name_filters=[name_filter] if name_filter else None,
            limit=limit,
        )
    )
    if as_json:
        _echo_json(hits)
        return
    for hit in hits:
        node = hit.node
        location = f"{node.file_path}:{node.start_line}" if node.file_path else node.id
        click.echo(f"{hit.score:.2f}  {node.name} ({node.type})  {location}")


@graph_group.command("callers")
@click.argument("symbol")
@click.argument("repo", required=False)
@click.option("--repo", "repo_option", help="Repository id, name, or path.")
@click.option("--limit", default=20, show_default=True, type=int)
@click.option("--json", "as_json", is_flag=True, help="Print JSON output.")
@click.pass_context
def graph_callers(
    ctx: click.Context,
    symbol: str,
    repo: str | None,
    repo_option: str | None,
    limit: int,
    as_json: bool,
) -> None:
    """List graph nodes that call or reference SYMBOL."""
    _echo_relationships(ctx, repo_option or repo, symbol, "callers", limit, as_json)


@graph_group.command("callees")
@click.argument("symbol")
@click.argument("repo", required=False)
@click.option("--repo", "repo_option", help="Repository id, name, or path.")
@click.option("--limit", default=20, show_default=True, type=int)
@click.option("--json", "as_json", is_flag=True, help="Print JSON output.")
@click.pass_context
def graph_callees(
    ctx: click.Context,
    symbol: str,
    repo: str | None,
    repo_option: str | None,
    limit: int,
    as_json: bool,
) -> None:
    """List graph nodes called or referenced by SYMBOL."""
    _echo_relationships(ctx, repo_option or repo, symbol, "callees", limit, as_json)


@graph_group.command("impact")
@click.argument("symbol")
@click.argument("repo", required=False)
@click.option("--repo", "repo_option", help="Repository id, name, or path.")
@click.option("--depth", default=2, show_default=True, type=int)
@click.option("--json", "as_json", is_flag=True, help="Print JSON output.")
@click.pass_context
def graph_impact(
    ctx: click.Context,
    symbol: str,
    repo: str | None,
    repo_option: str | None,
    depth: int,
    as_json: bool,
) -> None:
    """Show symbols potentially affected by changing SYMBOL."""
    store = _store(ctx)
    selected_repo = _run_click_errors(lambda: _resolve_repo(store, repo_option or repo))
    result = _run_click_errors(lambda: GraphQueryService(store=store).impact(selected_repo.id, symbol, depth=depth))
    if as_json:
        _echo_json(result)
        return
    click.echo(f"Impact: {len(result.nodes)} nodes, {len(result.edges)} edges")
    for node in sorted(result.nodes, key=lambda item: (item.file_path, item.start_line or 0, item.name))[:80]:
        location = f"{node.file_path}:{node.start_line}" if node.file_path else node.id
        click.echo(f"- {node.name} ({node.type}) {location}")


@graph_group.command("explore")
@click.argument("query")
@click.argument("repo", required=False)
@click.option("--repo", "repo_option", help="Repository id, name, or path.")
@click.option("--max-files", default=12, show_default=True, type=int)
@click.option("--max-nodes", default=160, show_default=True, type=int)
@click.option("--json", "as_json", is_flag=True, help="Print JSON output.")
@click.pass_context
def graph_explore(
    ctx: click.Context,
    query: str,
    repo: str | None,
    repo_option: str | None,
    max_files: int,
    max_nodes: int,
    as_json: bool,
) -> None:
    """Build an exploration context grouped by relevant source sections."""
    store = _store(ctx)
    selected_repo = _run_click_errors(lambda: _resolve_repo(store, repo_option or repo))
    result = _run_click_errors(
        lambda: GraphQueryService(store=store).explore(
            selected_repo.id,
            query,
            max_files=max_files,
            max_nodes=max_nodes,
        )
    )
    if as_json:
        _echo_json(result)
        return
    click.echo(result.text)


@graph_group.command("affected")
@click.argument("files", nargs=-1)
@click.option("--repo", "repo_option", help="Repository id, name, or path.")
@click.option("--stdin", "use_stdin", is_flag=True, help="Read changed files from stdin.")
@click.option("--depth", default=5, show_default=True, type=int)
@click.option("--test-glob", help="Custom glob used to identify test files.")
@click.option("--json", "as_json", is_flag=True, help="Print JSON output.")
@click.pass_context
def graph_affected(
    ctx: click.Context,
    files: tuple[str, ...],
    repo_option: str | None,
    use_stdin: bool,
    depth: int,
    test_glob: str | None,
    as_json: bool,
) -> None:
    """Find files, tests, and wiki pages affected by changed files."""
    store = _store(ctx)
    selected_repo = _run_click_errors(lambda: _resolve_repo(store, repo_option))
    changed_files = list(files)
    if use_stdin:
        changed_files.extend(
            line.strip() for line in click.get_text_stream("stdin").read().splitlines() if line.strip()
        )
    result = _run_click_errors(
        lambda: GraphQueryService(store=store).affected(
            selected_repo.id,
            changed_files,
            depth=depth,
            test_glob=test_glob,
        )
    )
    if as_json:
        _echo_json(result)
        return
    click.echo(f"Affected files: {len(result.affected_files)}")
    if result.affected_tests:
        click.echo("Affected tests:")
        for file_path in result.affected_tests:
            click.echo(f"- {file_path}")
    if result.affected_wiki_pages:
        click.echo("Affected wiki pages:")
        for slug in result.affected_wiki_pages:
            click.echo(f"- {slug}")


@graph_group.command("status")
@click.argument("repo", required=False)
@click.option("--repo", "repo_option", help="Repository id, name, or path.")
@click.option("--json", "as_json", is_flag=True, help="Print JSON output.")
@click.pass_context
def graph_status(
    ctx: click.Context,
    repo: str | None,
    repo_option: str | None,
    as_json: bool,
) -> None:
    """Show graph index statistics."""
    store = _store(ctx)
    selected_repo = _run_click_errors(lambda: _resolve_repo(store, repo_option or repo))
    nodes, edges = _run_click_errors(lambda: store.get_graph(selected_repo.id))
    payload = _graph_status_payload(selected_repo.id, nodes, edges)
    if as_json:
        _echo_json(payload)
        return
    click.echo(
        f"{payload['node_count']} nodes, {payload['edge_count']} edges, "
        f"{payload['file_count']} files"
    )
    _echo_table(["type", "count"], [[key, value] for key, value in payload["nodes_by_type"].items()])


@main.group("wiki")
def wiki_group() -> None:
    """Generate wiki catalog and pages."""


@wiki_group.command("catalog")
@click.argument("repo", required=False)
@click.option("--json", "as_json", is_flag=True, help="Print JSON output.")
@click.pass_context
def generate_catalog(ctx: click.Context, repo: str | None, as_json: bool) -> None:
    """Generate a wiki catalog for REPO."""
    store = _store(ctx)
    selected_repo = _run_click_errors(lambda: _resolve_repo(store, repo))
    catalog = _run_click_errors(
        lambda: asyncio.run(_wiki_generator(store).generate_catalog(selected_repo.id)),
        capture_stdout=as_json,
    )
    payload = _jsonable(catalog)
    if as_json:
        _echo_json(payload)
        return
    click.echo(f"Catalog generated: {catalog.title} ({catalog.id})")


@wiki_group.command("pages")
@click.argument("repo", required=False)
@click.option("--json", "as_json", is_flag=True, help="Print JSON output.")
@click.pass_context
def generate_pages(ctx: click.Context, repo: str | None, as_json: bool) -> None:
    """Generate all wiki pages for REPO."""
    store = _store(ctx)
    selected_repo = _run_click_errors(lambda: _resolve_repo(store, repo))
    results = _run_click_errors(
        lambda: asyncio.run(_wiki_generator(store).generate_all_pages(selected_repo.id)),
        capture_stdout=as_json,
    )
    payload = [_page_result_payload(result) for result in results]
    if as_json:
        _echo_json(payload)
        return
    generated = sum(1 for result in results if result.page.status == "generated")
    click.echo(f"Generated {generated}/{len(results)} wiki pages")


@wiki_group.command("update")
@click.argument("repo", required=False)
@click.option("--language", default="en", show_default=True, help="Wiki language to update.")
@click.option("--json", "as_json", is_flag=True, help="Print JSON output.")
@click.pass_context
def update_wiki_pages(
    ctx: click.Context,
    repo: str | None,
    language: str,
    as_json: bool,
) -> None:
    """Incrementally generate missing or stale wiki pages for REPO."""
    store = _store(ctx)
    selected_repo = _run_click_errors(lambda: _resolve_repo(store, repo))
    update = _run_click_errors(
        lambda: asyncio.run(_wiki_generator(store).update_pages(selected_repo.id, language_code=language)),
        capture_stdout=as_json,
    )
    payload = {
        "repo_id": selected_repo.id,
        "language_code": update.language_code,
        "generated_pages": update.generated_slugs,
        "reused_count": len(update.reused_pages),
        "stale_pages": update.stale_slugs,
        "missing_pages": update.missing_slugs,
        "deleted_page_count": update.deleted_page_count,
        "pages": [_page_result_payload(result) for result in update.results],
    }
    if as_json:
        _echo_json(payload)
        return
    click.echo(
        f"Wiki update: {len(update.generated_slugs)} generated, "
        f"{len(update.reused_pages)} reused ({update.language_code})"
    )


@wiki_group.command("page")
@click.argument("slug")
@click.argument("repo", required=False)
@click.option("--repo", "repo_option", help="Repository id, name, or path.")
@click.option("--json", "as_json", is_flag=True, help="Print JSON output.")
@click.pass_context
def regenerate_page(
    ctx: click.Context,
    slug: str,
    repo: str | None,
    repo_option: str | None,
    as_json: bool,
) -> None:
    """Regenerate one wiki page by SLUG."""
    store = _store(ctx)
    selected_repo = _run_click_errors(lambda: _resolve_repo(store, repo_option or repo))
    result = _run_click_errors(
        lambda: asyncio.run(_wiki_generator(store).regenerate_page(selected_repo.id, slug)),
        capture_stdout=as_json,
    )
    payload = _page_result_payload(result)
    if as_json:
        _echo_json(payload)
        return
    click.echo(f"Page {result.page.status}: {result.page.slug}")


@main.command("ask")
@click.argument("args", nargs=-1, required=True)
@click.option("--repo", "repo_option", help="Repository id, name, or path. Defaults to current directory.")
@click.option("--max-hops", default=2, show_default=True, type=click.IntRange(0, 4))
@click.option("--json", "as_json", is_flag=True, help="Print JSON output.")
@click.pass_context
def ask_repo(
    ctx: click.Context,
    args: tuple[str, ...],
    repo_option: str | None,
    max_hops: int,
    as_json: bool,
) -> None:
    """Ask a GraphRAG grounded QUESTION.

    Usage examples:
      codewiki ask "How is auth wired?"
      codewiki ask --repo backend "How is auth wired?"
      codewiki ask backend "How is auth wired?"
    """
    store = _store(ctx)
    settings = get_settings()
    repo_selector, question = _parse_ask_args(store, args, repo_option)
    selected_repo = _run_click_errors(lambda: _resolve_repo(store, repo_selector))
    answer = _run_click_errors(
        lambda: asyncio.run(
            QuestionAnswerer(
                GraphRAGRetriever(store=store, settings=settings),
                LLMGateway(settings),
                store=store,
            ).answer(selected_repo.id, AskRequest(question=question, max_hops=max_hops))
        ),
        capture_stdout=as_json,
    )
    payload = _jsonable(answer)
    if as_json:
        _echo_json(payload)
        return
    click.echo(answer.answer)


@main.command("serve")
@click.option("--host", default="127.0.0.1", show_default=True, help="Host for the FastAPI server.")
@click.option("--port", default=8000, show_default=True, type=int, help="Port for the FastAPI server.")
@click.option("--reload", is_flag=True, help="Reload when backend source files change.")
def serve(host: str, port: int, reload: bool) -> None:
    """Start the CodeWiki FastAPI server."""
    import uvicorn

    uvicorn.run("backend.app.main:app", host=host, port=port, reload=reload)


@main.command("mcp")
def serve_mcp() -> None:
    """Start the CodeWiki MCP server over stdio."""
    from backend.app.mcp_server import main as mcp_main

    mcp_main()


def _config_updates(
    *,
    assignment_values: tuple[str, ...],
    profile: str,
    model: str | None,
    provider_type: str | None,
    endpoint: str | None,
    api_key: str | None,
    base_language: str | None,
    translation_languages: str | None,
) -> dict[str, str]:
    updates: dict[str, str] = {}
    for raw_assignment in assignment_values:
        assignment = parse_env_assignment(raw_assignment)
        updates[assignment.key] = assignment.value

    profile_options = {
        "MODEL": model,
        "PROVIDER_TYPE": provider_type,
        "ENDPOINT": endpoint,
        "API_KEY": api_key,
    }
    for field, value in profile_options.items():
        if value is not None:
            updates[llm_profile_key(profile, field)] = value

    if base_language is not None:
        updates["CODEWIKI_WIKI_BASE_LANGUAGE"] = base_language
    if translation_languages is not None:
        updates["CODEWIKI_WIKI_TRANSLATION_LANGUAGES"] = translation_languages
    return updates


def _prompt_config_values(values: dict[str, str]) -> dict[str, str]:
    click.echo("Configuring CodeWiki environment variables.")
    updates: dict[str, str] = {}
    updates["CODEWIKI_LLM__MODE"] = click.prompt(
        "LLM mode",
        type=click.Choice(["sdk", "proxy"]),
        default=values.get("CODEWIKI_LLM__MODE") or "sdk",
    )
    updates["CODEWIKI_LLM__DEFAULT__MODEL"] = click.prompt(
        "Default model",
        default=values.get("CODEWIKI_LLM__DEFAULT__MODEL") or "provider/strong-coding-model",
    )
    updates["CODEWIKI_LLM__DEFAULT__PROVIDER_TYPE"] = click.prompt(
        "Default provider type",
        default=values.get("CODEWIKI_LLM__DEFAULT__PROVIDER_TYPE", ""),
        show_default=False,
    )
    updates["CODEWIKI_LLM__DEFAULT__ENDPOINT"] = click.prompt(
        "Default endpoint",
        default=values.get("CODEWIKI_LLM__DEFAULT__ENDPOINT", ""),
        show_default=False,
    )
    api_key = click.prompt(
        "Default API key (leave blank to keep current)",
        default="",
        hide_input=True,
        show_default=False,
    )
    if api_key:
        updates["CODEWIKI_LLM__DEFAULT__API_KEY"] = api_key

    updates["CODEWIKI_WIKI_BASE_LANGUAGE"] = click.prompt(
        "Wiki base language",
        default=values.get("CODEWIKI_WIKI_BASE_LANGUAGE") or "en",
    )
    updates["CODEWIKI_WIKI_TRANSLATION_LANGUAGES"] = click.prompt(
        "Wiki translation languages",
        default=values.get("CODEWIKI_WIKI_TRANSLATION_LANGUAGES", ""),
        show_default=False,
    )
    return updates


def _echo_config_update(
    env_file: Path,
    created: bool,
    updates: dict[str, str],
    *,
    show_secrets: bool,
    as_json: bool,
) -> None:
    payload = {
        "env_file": str(env_file),
        "created": created,
        "updated": mask_config_values(updates, show_secrets=show_secrets),
    }
    if as_json:
        _echo_json(payload)
        return

    if created:
        click.echo(f"Created {env_file}")
    if updates:
        click.echo(f"Updated {env_file}")
        _echo_table(
            ["key", "value"],
            [[key, value] for key, value in payload["updated"].items()],
        )
        return
    click.echo(f"No changes made to {env_file}")


def _echo_config_values(
    values: dict[str, str],
    *,
    show_secrets: bool,
    as_json: bool,
    env_file: Path | None = None,
) -> None:
    masked_values = mask_config_values(values, show_secrets=show_secrets)
    if as_json:
        payload: dict[str, object] = {"values": masked_values}
        if env_file is not None:
            payload["env_file"] = str(env_file)
        _echo_json(payload)
        return

    if not masked_values:
        if env_file is None:
            click.echo("No values found.")
        else:
            click.echo(f"No CODEWIKI_* values configured in {env_file}.")
        return
    _echo_table(["key", "value"], [[key, value] for key, value in masked_values.items()])


def _store(ctx: click.Context) -> SQLiteStore:
    obj = ctx.ensure_object(dict)
    store = obj.get("store")
    if store is None:
        store = get_store()
        obj["store"] = store
    if not isinstance(store, SQLiteStore):
        raise click.ClickException("CLI store is not initialized.")
    return store


def _wiki_generator(store: SQLiteStore) -> WikiGenerator:
    settings = get_settings()
    return WikiGenerator(
        GraphRAGRetriever(store=store, settings=settings),
        LLMGateway(settings),
        store=store,
        settings=settings,
    )


def _echo_relationships(
    ctx: click.Context,
    repo_selector: str | None,
    symbol: str,
    mode: str,
    limit: int,
    as_json: bool,
) -> None:
    store = _store(ctx)
    selected_repo = _run_click_errors(lambda: _resolve_repo(store, repo_selector))
    service = GraphQueryService(store=store)
    relationships = _run_click_errors(
        lambda: (
            service.callers(selected_repo.id, symbol, limit=limit)
            if mode == "callers"
            else service.callees(selected_repo.id, symbol, limit=limit)
        )
    )
    if as_json:
        _echo_json(relationships)
        return
    for item in relationships:
        source = item.source
        target = item.target
        click.echo(
            f"{source.name} ({source.type}) -[{item.edge.type}]-> "
            f"{target.name} ({target.type})"
        )


def _graph_status_payload(repo_id: str, nodes, edges) -> dict[str, object]:
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


def _resolve_repo(
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


def _parse_ask_args(
    store: SQLiteStore,
    args: tuple[str, ...],
    repo_option: str | None,
) -> tuple[str | None, str]:
    if repo_option:
        return repo_option, " ".join(args).strip()
    if len(args) == 1:
        return None, args[0]

    possible_repo = args[0]
    if _can_resolve_repo_selector(store, possible_repo):
        return possible_repo, " ".join(args[1:]).strip()
    return None, " ".join(args).strip()


def _can_resolve_repo_selector(store: SQLiteStore, selector: str) -> bool:
    try:
        _resolve_repo(store, selector, auto_register_paths=False)
    except ValueError:
        return False
    return True


def _repo_payload(repo: RepoDescriptor) -> dict[str, object]:
    return _jsonable(repo)


def _scan_payload(scan: RepoScanResult) -> dict[str, object]:
    return _jsonable(scan)


def _page_result_payload(result) -> dict[str, object]:
    return {
        "page": _jsonable(result.page),
        "validation_errors": result.validation_errors,
    }


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump())
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def _echo_json(payload: Any) -> None:
    click.echo(json.dumps(_jsonable(payload), indent=2, sort_keys=True))


def _echo_table(headers: list[str], rows: list[list[str]]) -> None:
    widths = [
        max(len(headers[index]), *(len(str(row[index])) for row in rows))
        for index in range(len(headers))
    ]
    click.echo("  ".join(header.ljust(widths[index]) for index, header in enumerate(headers)))
    click.echo("  ".join("-" * width for width in widths))
    for row in rows:
        click.echo("  ".join(str(value).ljust(widths[index]) for index, value in enumerate(row)))


def _run_click_errors(callback, *, capture_stdout: bool = False):
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


if __name__ == "__main__":
    main()
