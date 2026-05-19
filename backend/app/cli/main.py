import os

import click

from backend.app.config import get_settings
from backend.app.database import get_store
from backend.app.cli import analysis, ask, config, graph, graphrag, repos, serve, wiki


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


repos.register(main)
config.register(main)
analysis.register(main)
graphrag.register(main)
graph.register(main)
wiki.register(main)
ask.register(main)
serve.register(main)


if __name__ == "__main__":
    main()
