import asyncio

import click

from backend.app.cli.common import echo_json, page_result_payload, resolve_repo, run_click_errors, store_from_context
from backend.app.cli.services import wiki_generator


def register(main: click.Group) -> None:
    @main.group("wiki")
    def wiki_group() -> None:
        """Generate wiki catalog and pages."""

    @wiki_group.command("catalog")
    @click.argument("repo", required=False)
    @click.option("--json", "as_json", is_flag=True, help="Print JSON output.")
    @click.pass_context
    def generate_catalog(ctx: click.Context, repo: str | None, as_json: bool) -> None:
        """Generate a wiki catalog for REPO."""
        store = store_from_context(ctx)
        selected_repo = run_click_errors(lambda: resolve_repo(store, repo))
        catalog = run_click_errors(
            lambda: asyncio.run(wiki_generator(store).generate_catalog(selected_repo.id)),
            capture_stdout=as_json,
        )
        if as_json:
            echo_json(catalog)
            return
        click.echo(f"Catalog generated: {catalog.title} ({catalog.id})")

    @wiki_group.command("pages")
    @click.argument("repo", required=False)
    @click.option("--json", "as_json", is_flag=True, help="Print JSON output.")
    @click.pass_context
    def generate_pages(ctx: click.Context, repo: str | None, as_json: bool) -> None:
        """Generate all wiki pages for REPO."""
        store = store_from_context(ctx)
        selected_repo = run_click_errors(lambda: resolve_repo(store, repo))
        results = run_click_errors(
            lambda: asyncio.run(wiki_generator(store).generate_all_pages(selected_repo.id)),
            capture_stdout=as_json,
        )
        payload = [page_result_payload(result) for result in results]
        if as_json:
            echo_json(payload)
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
        store = store_from_context(ctx)
        selected_repo = run_click_errors(lambda: resolve_repo(store, repo))
        update = run_click_errors(
            lambda: asyncio.run(wiki_generator(store).update_pages(selected_repo.id, language_code=language)),
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
            "pages": [page_result_payload(result) for result in update.results],
        }
        if as_json:
            echo_json(payload)
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
        store = store_from_context(ctx)
        selected_repo = run_click_errors(lambda: resolve_repo(store, repo_option or repo))
        result = run_click_errors(
            lambda: asyncio.run(wiki_generator(store).regenerate_page(selected_repo.id, slug)),
            capture_stdout=as_json,
        )
        payload = page_result_payload(result)
        if as_json:
            echo_json(payload)
            return
        click.echo(f"Page {result.page.status}: {result.page.slug}")
