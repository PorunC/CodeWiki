from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.frontend import mount_frontend


def test_mount_frontend_serves_static_assets_and_spa_routes(tmp_path: Path) -> None:
    static_dir = tmp_path / "static"
    assets_dir = static_dir / "assets"
    assets_dir.mkdir(parents=True)
    (static_dir / "index.html").write_text("<div id='root'></div>", encoding="utf-8")
    (assets_dir / "app.js").write_text("console.log('codewiki')", encoding="utf-8")

    app = FastAPI()

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    mount_frontend(app, static_dir=static_dir)
    client = TestClient(app)

    root_response = client.get("/")
    assert root_response.status_code == 200
    assert "<div id='root'></div>" in root_response.text

    spa_response = client.get("/repos/example/wiki")
    assert spa_response.status_code == 200
    assert "<div id='root'></div>" in spa_response.text

    asset_response = client.get("/assets/app.js")
    assert asset_response.status_code == 200
    assert "console.log('codewiki')" in asset_response.text

    api_response = client.get("/api/health")
    assert api_response.status_code == 200
    assert api_response.json() == {"status": "ok"}

    missing_api_response = client.get("/api/missing")
    assert missing_api_response.status_code == 404


def test_mount_frontend_is_noop_without_built_index(tmp_path: Path) -> None:
    app = FastAPI()
    mount_frontend(app, static_dir=tmp_path / "missing")

    response = TestClient(app).get("/")

    assert response.status_code == 404
