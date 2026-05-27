import os

import click

from backend.app.config import get_settings
from backend.app.database import get_store
from backend.app.cli import analysis, ask, config, files, graph, graphrag, lite, repos, serve, wiki


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.option(
    "--database-url",
    envvar="CODEWIKI_DATABASE_URL",
    help=(
        "Database URL. Supports sqlite+aiosqlite:///path and "
        "postgresql+psycopg://user:pass@host:5432/db."
    ),
)
@click.pass_context
def main(ctx: click.Context, database_url: str | None) -> None:
    """Code Wiki command line tools.

    Lite mode keeps a no-LLM index in the current project's .codewiki directory:

    \b
      codewiki lite index .
      codewiki lite status .
      codewiki lite sync .   # or: codewiki lite watch .
      codewiki mcp --lite --path .
    """
    if database_url:
        if get_store.cache_info().currsize:
            get_store().close()
        os.environ["CODEWIKI_DATABASE_URL"] = database_url
        get_settings.cache_clear()
        get_store.cache_clear()
    ctx.obj = {"store": None}


repos.register(main)
config.register(main)
analysis.register(main)
graphrag.register(main)
graph.register(main)
files.register(main)
wiki.register(main)
ask.register(main)
lite.register(main)
serve.register(main)


if __name__ == "__main__":
    main()
