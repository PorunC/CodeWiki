from __future__ import annotations

import os
import shutil
from importlib import resources
from pathlib import Path

import click

from backend.app.cli.common import echo_json, run_click_errors


def register(main: click.Group) -> None:
    @main.group("skill")
    def skill_group() -> None:
        """Install CodeWiki agent skills."""

    @skill_group.command("install")
    @click.argument("target", type=click.Choice(["codex"]))
    @click.option("--json", "as_json", is_flag=True, help="Print JSON output.")
    def install_skill(target: str, as_json: bool) -> None:
        """Install the CodeWiki skill for an agent target."""

        def install() -> dict[str, str]:
            destination = _codex_home() / "skills" / "codewiki"
            destination.parent.mkdir(parents=True, exist_ok=True)
            with resources.as_file(resources.files("backend.skills.codewiki")) as source:
                if not source.exists():
                    raise ValueError(f"CodeWiki skill bundle not found: {source}")
                shutil.copytree(
                    source,
                    destination,
                    dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__init__.py", "__pycache__", "*.pyc"),
                )
                payload = {
                    "target": target,
                    "status": "installed",
                    "source": str(source),
                    "destination": str(destination),
                }
            return payload

        payload = run_click_errors(install)
        if as_json:
            echo_json(payload)
            return
        click.echo(f"Installed CodeWiki skill to {payload['destination']}")


def _codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
