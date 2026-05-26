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
    def serve_mcp() -> None:
        """Start the CodeWiki MCP server over stdio."""
        from backend.app.mcp_server import main as mcp_main

        mcp_main()
