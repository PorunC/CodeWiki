import asyncio

import click

from backend.app.cli.common import echo_json, parse_ask_args, resolve_repo, run_click_errors, store_from_context
from backend.app.cli.services import question_answerer
from backend.app.schemas.ask import AskRequest


def register(main: click.Group) -> None:
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
        store = store_from_context(ctx)
        repo_selector, question = parse_ask_args(store, args, repo_option)
        selected_repo = run_click_errors(lambda: resolve_repo(store, repo_selector))
        answer = run_click_errors(
            lambda: asyncio.run(
                question_answerer(store).answer(
                    selected_repo.id,
                    AskRequest(question=question, max_hops=max_hops),
                )
            ),
            capture_stdout=as_json,
        )
        if as_json:
            echo_json(answer)
            return
        click.echo(answer.answer)
