from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


FRONTEND_STATIC_DIR = Path(__file__).resolve().parent / "static"


def mount_frontend(app: FastAPI, static_dir: Path = FRONTEND_STATIC_DIR) -> None:
    index_html = static_dir / "index.html"
    if not index_html.is_file():
        return

    assets_dir = static_dir / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="frontend-assets")

    static_root = static_dir.resolve()

    @app.get("/", include_in_schema=False)
    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_frontend(full_path: str = "") -> FileResponse:
        if _reserved_backend_path(full_path):
            raise HTTPException(status_code=404)

        if full_path:
            target = (static_root / full_path).resolve()
            if _inside_directory(target, static_root) and target.is_file():
                return FileResponse(target)

        return FileResponse(index_html)


def _reserved_backend_path(path: str) -> bool:
    return path == "api" or path.startswith("api/")


def _inside_directory(path: Path, directory: Path) -> bool:
    return path == directory or directory in path.parents
