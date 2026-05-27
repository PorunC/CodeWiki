from pathlib import Path

import click


def register(main: click.Group) -> None:
    @main.command("serve")
    @click.option("--host", default="127.0.0.1", show_default=True, help="Host for the FastAPI server.")
    @click.option("--port", default=8000, show_default=True, type=int, help="Port for the FastAPI server.")
    @click.option("--reload", is_flag=True, help="Reload when backend source files change.")
    def serve(host: str, port: int, reload: bool) -> None:
        """Start the CodeWiki FastAPI server."""
        import uvicorn

        reload_dirs: list[str] | None = None
        reload_excludes: list[str] | None = None
        if reload:
            reload_dirs = [str(Path(__file__).resolve().parents[2])]
            reload_excludes = ["storage/*", "data/*"]
        uvicorn.run(
            "backend.app.main:app",
            host=host,
            port=port,
            reload=reload,
            reload_dirs=reload_dirs,
            reload_excludes=reload_excludes,
        )

    @main.command("mcp")
    @click.option("--lite", is_flag=True, help="Use the project-local .codewiki lite database.")
    @click.option("--path", default=".", show_default=True, help="Repository path for --lite.")
    @click.option("--no-sync", is_flag=True, help="Do not catch up the lite index before serving MCP.")
    def serve_mcp(lite: bool, path: str, no_sync: bool) -> None:
        """Start the CodeWiki MCP server over stdio."""
        import asyncio

        from backend.app.mcp_server.server import CodeWikiMCPServer
        from backend.app.mcp_server.transport import run_stdio
        from backend.app.services.lite import prepare_lite_mcp_store

        store = prepare_lite_mcp_store(path=path, sync=not no_sync) if lite else None
        asyncio.run(run_stdio(CodeWikiMCPServer(store=store)))
