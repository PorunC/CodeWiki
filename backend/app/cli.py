import asyncio
import json
import os
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

import click

from backend.app.config import get_settings
from backend.app.database import SQLiteStore, get_store
from backend.app.schemas.ask import AskRequest
from backend.app.services.analyzer import AnalysisService
from backend.app.services.graph_rag import GraphRAGRetriever
from backend.app.services.incremental_updater import IncrementalUpdater
from backend.app.services.llm_gateway import LLMGateway
from backend.app.services.question_answerer import QuestionAnswerer
from backend.app.services.repo_scanner import RepoDescriptor, RepoScanResult, RepoScanner
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
    ctx.obj = {"store": get_store()}


@main.group("repos")
def repos_group() -> None:
    """Register and inspect repositories."""


@repos_group.command("add")
@click.argument("path", type=click.Path(exists=True, file_okay=False, path_type=str))
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
    """Register PATH in the local Code Wiki database."""
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
@click.argument("path", type=click.Path(exists=True, file_okay=False, path_type=str))
@click.option("--name", help="Repository display name.")
@click.option("--source-type", default="local", show_default=True)
@click.option("--json", "as_json", is_flag=True, help="Print JSON output.")
def scan_repo(path: str, name: str | None, source_type: str, as_json: bool) -> None:
    """Scan PATH without registering it."""
    scan = _run_click_errors(lambda: RepoScanner().scan(path, name=name, source_type=source_type))
    if as_json:
        _echo_json(_scan_payload(scan))
        return
    click.echo(f"Repo: {scan.repo.name} ({scan.repo.id})")
    click.echo(f"Scanned: {scan.scanned_count}")
    click.echo(f"Ignored: {scan.ignored_count}")
    click.echo(f"Skipped: {scan.skipped_count}")


@main.command("analyze")
@click.argument("repo", required=False)
@click.option("--json", "as_json", is_flag=True, help="Print JSON output.")
@click.pass_context
def analyze_repo(ctx: click.Context, repo: str | None, as_json: bool) -> None:
    """Run full AST graph analysis for REPO.

    REPO can be an id, id prefix, registered name, path, or omitted for the
    current directory.
    """
    store = _store(ctx)
    selected_repo = _run_click_errors(lambda: _resolve_repo(store, repo))
    result = _run_click_errors(lambda: AnalysisService(store=store).analyze(selected_repo.id))
    payload = {
        "run_id": result.run_id,
        "repo_id": result.repo_id,
        "status": result.status,
        **result.stats(),
    }
    if as_json:
        _echo_json(payload)
        return
    click.echo(
        f"Analysis {result.status}: {result.node_count} nodes, "
        f"{result.edge_count} edges, {result.community_count} communities"
    )
    click.echo(f"Run: {result.run_id}")


@main.command("update")
@click.argument("repo", required=False)
@click.option("--refresh-chunks/--no-refresh-chunks", default=True, show_default=True)
@click.option("--regenerate-wiki/--no-regenerate-wiki", default=False, show_default=True)
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
    result = _run_click_errors(
        lambda: IncrementalUpdater(store=store).update(selected_repo.id, refresh_chunks=refresh_chunks)
    )
    wiki_regeneration = (
        asyncio.run(_regenerate_stale_wiki_pages(store, selected_repo.id, result.stale_pages))
        if regenerate_wiki
        else {"requested": False, "pages": [], "errors": [], "skipped_pages": result.stale_pages}
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
        )
    )
    payload = _jsonable(result)
    if as_json:
        _echo_json(payload)
        return
    click.echo(f"GraphRAG {result.status}: {result.chunk_count} chunks")
    if result.embedding_count:
        click.echo(f"Embeddings: {result.embedding_count} ({result.embedding_model})")


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
        lambda: asyncio.run(_wiki_generator(store).generate_catalog(selected_repo.id))
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
        lambda: asyncio.run(_wiki_generator(store).generate_all_pages(selected_repo.id))
    )
    payload = [_page_result_payload(result) for result in results]
    if as_json:
        _echo_json(payload)
        return
    generated = sum(1 for result in results if result.page.status == "generated")
    click.echo(f"Generated {generated}/{len(results)} wiki pages")


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
        lambda: asyncio.run(_wiki_generator(store).regenerate_page(selected_repo.id, slug))
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
        )
    )
    payload = _jsonable(answer)
    if as_json:
        _echo_json(payload)
        return
    click.echo(answer.answer)


def _store(ctx: click.Context) -> SQLiteStore:
    obj = ctx.ensure_object(dict)
    store = obj.get("store")
    if not isinstance(store, SQLiteStore):
        raise click.ClickException("CLI store is not initialized.")
    return store


def _wiki_generator(store: SQLiteStore) -> WikiGenerator:
    settings = get_settings()
    return WikiGenerator(
        GraphRAGRetriever(store=store, settings=settings),
        LLMGateway(settings),
        store=store,
    )


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

    raise ValueError(
        f"Repository not found: {selector}. Use a repo id, id prefix, name, path, "
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


async def _regenerate_stale_wiki_pages(
    store: SQLiteStore,
    repo_id: str,
    stale_pages: list[str],
) -> dict[str, object]:
    if not stale_pages:
        return {"requested": True, "pages": [], "errors": []}
    generator = _wiki_generator(store)
    pages: list[dict[str, object]] = []
    errors: list[dict[str, str]] = []
    for slug in stale_pages:
        try:
            result = await generator.regenerate_page(repo_id, slug)
        except Exception as exc:
            errors.append({"slug": slug, "error": str(exc)})
            continue
        pages.append(
            {
                "slug": result.page.slug,
                "status": result.page.status,
                "validation_errors": result.validation_errors,
            }
        )
    return {"requested": True, "pages": pages, "errors": errors}


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


def _run_click_errors(callback):
    try:
        return callback()
    except (FileNotFoundError, NotADirectoryError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc


if __name__ == "__main__":
    main()
