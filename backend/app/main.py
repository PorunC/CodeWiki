from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api import ask, files, graph, repos, runs, settings, wiki
from backend.app.config import get_settings


def create_app() -> FastAPI:
    app_settings = get_settings()
    app = FastAPI(title=app_settings.app_name)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(repos.router, prefix="/api/repos", tags=["repos"])
    app.include_router(files.router, prefix="/api/repos", tags=["files"])
    app.include_router(graph.router, prefix="/api/repos", tags=["graph"])
    app.include_router(wiki.router, prefix="/api/repos", tags=["wiki"])
    app.include_router(ask.router, prefix="/api/repos", tags=["ask"])
    app.include_router(runs.router, prefix="/api/repos", tags=["runs"])
    app.include_router(settings.router, prefix="/api/settings", tags=["settings"])

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
