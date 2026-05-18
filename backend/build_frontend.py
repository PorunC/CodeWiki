from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from setuptools.command.build_py import build_py as _build_py
from setuptools.command.sdist import sdist as _sdist


ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = ROOT / "frontend"
FRONTEND_STATIC_DIR = ROOT / "backend" / "app" / "static"


class build_py(_build_py):
    def run(self) -> None:
        build_frontend()
        super().run()


class sdist(_sdist):
    def run(self) -> None:
        build_frontend()
        super().run()


def build_frontend() -> None:
    if _env_flag("CODEWIKI_SKIP_FRONTEND_BUILD"):
        return

    package_json = FRONTEND_DIR / "package.json"
    index_html = FRONTEND_STATIC_DIR / "index.html"
    if not package_json.exists():
        if index_html.exists():
            return
        raise RuntimeError(
            "Frontend source is missing and no prebuilt frontend was found at "
            f"{index_html}. Build the wheel from a full source checkout."
        )

    npm = shutil.which(os.environ.get("NPM", "npm"))
    if npm is None:
        if index_html.exists():
            print("npm was not found; reusing existing backend/app/static frontend build.")
            return
        raise RuntimeError(
            "npm is required to build the CodeWiki frontend. Install Node.js/npm, "
            "or set CODEWIKI_SKIP_FRONTEND_BUILD=1 only if backend/app/static is already built."
        )

    if not (FRONTEND_DIR / "node_modules").is_dir():
        install_command = [npm, "ci"] if (FRONTEND_DIR / "package-lock.json").exists() else [npm, "install"]
        subprocess.run(install_command, cwd=FRONTEND_DIR, check=True)

    subprocess.run([npm, "run", "build"], cwd=FRONTEND_DIR, check=True)


def _env_flag(name: str) -> bool:
    value = os.environ.get(name)
    return value is not None and value.lower() not in {"", "0", "false", "no", "off"}
