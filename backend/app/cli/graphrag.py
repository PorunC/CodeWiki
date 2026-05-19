import asyncio

import click

from backend.app.cli.common import echo_json, jsonable, resolve_repo, run_click_errors, store_from_context
from backend.app.services.graphrag import GraphRAGRetriever


def register(main: click.Group) -> None:
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
        store = store_from_context(ctx)
        selected_repo = run_click_errors(lambda: resolve_repo(store, repo))
        result = run_click_errors(
            lambda: asyncio.run(
                GraphRAGRetriever(store=store).build_index(
                    selected_repo.id,
                    include_embeddings=embeddings,
                )
            ),
            capture_stdout=as_json,
        )
        payload = jsonable(result)
        if as_json:
            echo_json(payload)
            return
        click.echo(f"GraphRAG {result.status}: {result.chunk_count} chunks")
        if result.embedding_count:
            click.echo(f"Embeddings: {result.embedding_count} ({result.embedding_model})")
