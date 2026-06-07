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
    @click.option("--language", default="en", show_default=True, help="Wiki language to generate.")
    @click.option("--json", "as_json", is_flag=True, help="Print JSON output.")
    @click.pass_context
    def generate_catalog(
        ctx: click.Context,
        repo: str | None,
        language: str,
        as_json: bool,
    ) -> None:
        """Generate a wiki catalog for REPO."""
        store = store_from_context(ctx)
        selected_repo = run_click_errors(lambda: resolve_repo(store, repo))
        catalog = run_click_errors(
            lambda: asyncio.run(
                wiki_generator(store).generate_catalog(selected_repo.id, language_code=language)
            ),
            capture_stdout=as_json,
        )
        if as_json:
            echo_json(catalog)
            return
        click.echo(f"Catalog generated: {catalog.title} ({catalog.id})")

    @wiki_group.command("pages")
    @click.argument("repo", required=False)
    @click.option("--language", default="en", show_default=True, help="Wiki language to generate.")
    @click.option("--json", "as_json", is_flag=True, help="Print JSON output.")
    @click.pass_context
    def generate_pages(
        ctx: click.Context,
        repo: str | None,
        language: str,
        as_json: bool,
    ) -> None:
        """Generate all wiki pages for REPO."""
        store = store_from_context(ctx)
        selected_repo = run_click_errors(lambda: resolve_repo(store, repo))
        results = run_click_errors(
            lambda: asyncio.run(
                wiki_generator(store).generate_all_pages(selected_repo.id, language_code=language)
            ),
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

    @wiki_group.command("plan")
    @click.argument("repo", required=False)
    @click.option("--repo", "repo_option", help="Repository id, name, or path.")
    @click.option("--language", default="en", show_default=True, help="Wiki language to plan.")
    @click.option("--json", "as_json", is_flag=True, help="Print JSON output.")
    @click.pass_context
    def plan_agent_wiki(
        ctx: click.Context,
        repo: str | None,
        repo_option: str | None,
        language: str,
        as_json: bool,
    ) -> None:
        """Plan agent-generated wiki pages for REPO without calling an LLM."""
        store = store_from_context(ctx)
        selected_repo = run_click_errors(lambda: resolve_repo(store, repo_option or repo))
        payload = run_click_errors(
            lambda: asyncio.run(
                wiki_generator(store).agent_wiki_plan(selected_repo.id, language_code=language)
            ),
            capture_stdout=as_json,
        )
        if as_json:
            echo_json(payload)
            return
        pages = payload.get("pages") if isinstance(payload, dict) else []
        page_count = len(pages) if isinstance(pages, list) else 0
        click.echo(f"Planned {page_count} wiki pages")

    @wiki_group.command("evidence")
    @click.argument("slug")
    @click.argument("repo", required=False)
    @click.option("--repo", "repo_option", help="Repository id, name, or path.")
    @click.option("--language", default="en", show_default=True, help="Wiki language to read.")
    @click.option("--limit", default=12, show_default=True, type=int, help="Maximum source refs.")
    @click.option("--json", "as_json", is_flag=True, help="Print JSON output.")
    @click.pass_context
    def agent_wiki_evidence(
        ctx: click.Context,
        slug: str,
        repo: str | None,
        repo_option: str | None,
        language: str,
        limit: int,
        as_json: bool,
    ) -> None:
        """Return bounded evidence for one agent-generated wiki page."""
        store = store_from_context(ctx)
        selected_repo = run_click_errors(lambda: resolve_repo(store, repo_option or repo))
        payload = run_click_errors(
            lambda: asyncio.run(
                wiki_generator(store).agent_wiki_evidence(
                    selected_repo.id,
                    slug,
                    language_code=language,
                    limit=limit,
                )
            ),
            capture_stdout=as_json,
        )
        if as_json:
            echo_json(payload)
            return
        click.echo(f"Prepared evidence for {slug}")

    @wiki_group.command("save")
    @click.argument("slug")
    @click.argument("repo", required=False)
    @click.option("--repo", "repo_option", help="Repository id, name, or path.")
    @click.option("--language", default="en", show_default=True, help="Wiki language to save.")
    @click.option("--title", help="Page title.")
    @click.option("--parent-slug", help="Parent page slug.")
    @click.option("--stdin", "from_stdin", is_flag=True, help="Read Markdown from stdin.")
    @click.option("--json", "as_json", is_flag=True, help="Print JSON output.")
    @click.pass_context
    def save_agent_wiki_page(
        ctx: click.Context,
        slug: str,
        repo: str | None,
        repo_option: str | None,
        language: str,
        title: str | None,
        parent_slug: str | None,
        from_stdin: bool,
        as_json: bool,
    ) -> None:
        """Save agent-written Markdown for one wiki page."""
        if not from_stdin:
            raise click.ClickException("Use --stdin to provide Markdown content.")
        markdown = click.get_text_stream("stdin").read()
        store = store_from_context(ctx)
        selected_repo = run_click_errors(lambda: resolve_repo(store, repo_option or repo))
        payload = run_click_errors(
            lambda: asyncio.run(
                wiki_generator(store).save_agent_wiki_page(
                    selected_repo.id,
                    slug,
                    markdown,
                    language_code=language,
                    title=title,
                    parent_slug=parent_slug,
                )
            ),
            capture_stdout=as_json,
        )
        if as_json:
            echo_json(payload)
            return
        click.echo(f"Saved {slug} as {payload['status']}")

    @wiki_group.command("validate")
    @click.argument("slug")
    @click.argument("repo", required=False)
    @click.option("--repo", "repo_option", help="Repository id, name, or path.")
    @click.option("--language", default="en", show_default=True, help="Wiki language to validate.")
    @click.option("--json", "as_json", is_flag=True, help="Print JSON output.")
    @click.pass_context
    def validate_agent_wiki_page(
        ctx: click.Context,
        slug: str,
        repo: str | None,
        repo_option: str | None,
        language: str,
        as_json: bool,
    ) -> None:
        """Validate an agent-generated wiki page."""
        store = store_from_context(ctx)
        selected_repo = run_click_errors(lambda: resolve_repo(store, repo_option or repo))
        payload = run_click_errors(
            lambda: asyncio.run(
                wiki_generator(store).validate_agent_wiki_page(
                    selected_repo.id,
                    slug,
                    language_code=language,
                )
            ),
            capture_stdout=as_json,
        )
        if as_json:
            echo_json(payload)
            return
        click.echo(f"Wiki page {slug} is {payload['status']}")

    @wiki_group.command("page")
    @click.argument("slug")
    @click.argument("repo", required=False)
    @click.option("--repo", "repo_option", help="Repository id, name, or path.")
    @click.option("--language", default="en", show_default=True, help="Wiki language to regenerate.")
    @click.option("--json", "as_json", is_flag=True, help="Print JSON output.")
    @click.pass_context
    def regenerate_page(
        ctx: click.Context,
        slug: str,
        repo: str | None,
        repo_option: str | None,
        language: str,
        as_json: bool,
    ) -> None:
        """Regenerate one wiki page by SLUG."""
        store = store_from_context(ctx)
        selected_repo = run_click_errors(lambda: resolve_repo(store, repo_option or repo))
        result = run_click_errors(
            lambda: asyncio.run(
                wiki_generator(store).regenerate_page(
                    selected_repo.id,
                    slug,
                    language_code=language,
                )
            ),
            capture_stdout=as_json,
        )
        payload = page_result_payload(result)
        if as_json:
            echo_json(payload)
            return
        click.echo(f"Page {result.page.status}: {result.page.slug}")

    @wiki_group.command("list")
    @click.argument("repo", required=False)
    @click.option("--repo", "repo_option", help="Repository id, name, or path.")
    @click.option("--language", default="en", show_default=True, help="Wiki language to read.")
    @click.option("--json", "as_json", is_flag=True, help="Print JSON output.")
    @click.pass_context
    def list_wiki(
        ctx: click.Context,
        repo: str | None,
        repo_option: str | None,
        language: str,
        as_json: bool,
    ) -> None:
        """List generated wiki pages for REPO."""
        store = store_from_context(ctx)
        selected_repo = run_click_errors(lambda: resolve_repo(store, repo_option or repo))
        catalog = store.get_latest_doc_catalog(selected_repo.id, language_code=language)
        pages = store.list_doc_pages(selected_repo.id, language_code=language)
        payload = {
            "repo_id": selected_repo.id,
            "catalog": catalog,
            "items": catalog.structure.get("items", []) if catalog else [],
            "pages": pages,
        }
        if as_json:
            echo_json(payload)
            return
        if catalog:
            click.echo(f"{catalog.title} ({catalog.language_code})")
        if not pages:
            click.echo("No wiki pages generated.")
            return
        for page in pages:
            click.echo(f"{page.slug}  {page.title}  {page.status}")

    @wiki_group.command("read")
    @click.argument("slug")
    @click.argument("repo", required=False)
    @click.option("--repo", "repo_option", help="Repository id, name, or path.")
    @click.option("--language", default="en", show_default=True, help="Wiki language to read.")
    @click.option("--json", "as_json", is_flag=True, help="Print JSON output.")
    @click.pass_context
    def read_wiki_page(
        ctx: click.Context,
        slug: str,
        repo: str | None,
        repo_option: str | None,
        language: str,
        as_json: bool,
    ) -> None:
        """Read a generated wiki page by SLUG."""
        store = store_from_context(ctx)
        selected_repo = run_click_errors(lambda: resolve_repo(store, repo_option or repo))
        page = store.get_doc_page(selected_repo.id, slug, language_code=language)
        if page is None:
            raise click.ClickException(f"Wiki page not found: {slug}")
        if as_json:
            echo_json(page)
            return
        click.echo(page.markdown)

    @wiki_group.command("translate")
    @click.argument("target_language")
    @click.argument("repo", required=False)
    @click.option("--repo", "repo_option", help="Repository id, name, or path.")
    @click.option("--source-language", default="en", show_default=True, help="Source wiki language.")
    @click.option("--json", "as_json", is_flag=True, help="Print JSON output.")
    @click.pass_context
    def translate_wiki(
        ctx: click.Context,
        target_language: str,
        repo: str | None,
        repo_option: str | None,
        source_language: str,
        as_json: bool,
    ) -> None:
        """Translate a generated wiki into TARGET_LANGUAGE."""
        store = store_from_context(ctx)
        selected_repo = run_click_errors(lambda: resolve_repo(store, repo_option or repo))
        result = run_click_errors(
            lambda: asyncio.run(
                wiki_generator(store).translate_wiki(
                    selected_repo.id,
                    source_language=source_language,
                    target_language=target_language,
                )
            ),
            capture_stdout=as_json,
        )
        payload = {
            "repo_id": selected_repo.id,
            "source_language": result.source_language,
            "target_language": result.target_language,
            "catalog": result.catalog,
            "page_count": len(result.pages),
            "pages": result.pages,
        }
        if as_json:
            echo_json(payload)
            return
        click.echo(
            f"Translated {len(result.pages)} pages "
            f"from {result.source_language} to {result.target_language}"
        )
