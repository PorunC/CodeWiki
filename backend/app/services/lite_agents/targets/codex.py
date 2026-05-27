from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from backend.app.services.lite_agents.constants import (
    CODEWIKI_LITE_INSTRUCTIONS,
    CODEWIKI_LITE_SERVER_NAME,
)
from backend.app.services.lite_agents.io import (
    atomic_write,
    file_action_for_write,
    read_text,
    remove_marked_section,
    remove_toml_table,
    upsert_toml_table,
    write_marked_section,
)
from backend.app.services.lite_agents.mcp import mcp_server_config
from backend.app.services.lite_agents.types import (
    AgentFileResult,
    AgentInstallResult,
    InstallLocation,
)


class CodexLiteTarget:
    id: Literal["codex"] = "codex"

    def supports_location(self, location: InstallLocation) -> bool:
        return location == "global"

    def detected(self, *, location: InstallLocation, project: Path, home: Path) -> bool:
        return location == "global" and _config_dir(home).exists()

    def install(
        self,
        *,
        location: InstallLocation,
        project: Path,
        home: Path,
        auto_allow: bool,
    ) -> AgentInstallResult:
        if location != "global":
            return AgentInstallResult(
                target="codex",
                files=[],
                notes=["Codex CLI has no project-local config; use --location global."],
            )
        return AgentInstallResult(
            target="codex",
            files=[
                _write_mcp_entry(home=home, project=project),
                write_marked_section(_instructions_path(home), CODEWIKI_LITE_INSTRUCTIONS),
            ],
            notes=[],
        )

    def uninstall(
        self,
        *,
        location: InstallLocation,
        project: Path,
        home: Path,
    ) -> AgentInstallResult:
        if location != "global":
            return AgentInstallResult(
                target="codex",
                files=[],
                notes=["Codex CLI has no project-local config."],
            )
        return AgentInstallResult(
            target="codex",
            files=[
                _remove_mcp_entry(_config_path(home)),
                remove_marked_section(_instructions_path(home)),
            ],
            notes=[],
        )

    def print_config(
        self,
        *,
        location: InstallLocation,
        project: Path,
        home: Path,
    ) -> str:
        if location != "global":
            return "# Codex CLI has no project-local config; use --location global.\n"
        return f"# Add to {_config_path(home)}\n\n{_toml_block(project)}\n"


def _toml_block(project: Path) -> str:
    config = mcp_server_config(project)
    args = ", ".join(json.dumps(arg) for arg in config["args"])
    return (
        f"[mcp_servers.{CODEWIKI_LITE_SERVER_NAME}]\n"
        f"command = {json.dumps(config['command'])}\n"
        f"args = [{args}]\n"
    )


def _config_dir(home: Path) -> Path:
    return home / ".codex"


def _config_path(home: Path) -> Path:
    return _config_dir(home) / "config.toml"


def _instructions_path(home: Path) -> Path:
    return _config_dir(home) / "AGENTS.md"


def _write_mcp_entry(*, home: Path, project: Path) -> AgentFileResult:
    path = _config_path(home)
    existing = read_text(path)
    block = _toml_block(project).rstrip()
    next_content, changed = upsert_toml_table(
        existing,
        f"mcp_servers.{CODEWIKI_LITE_SERVER_NAME}",
        block,
    )
    if not changed:
        return AgentFileResult(path, "unchanged")
    action = file_action_for_write(path)
    atomic_write(path, next_content.rstrip() + "\n")
    return AgentFileResult(path, action)


def _remove_mcp_entry(path: Path) -> AgentFileResult:
    if not path.exists():
        return AgentFileResult(path, "not-found")
    existing = read_text(path)
    next_content, changed = remove_toml_table(existing, f"mcp_servers.{CODEWIKI_LITE_SERVER_NAME}")
    if not changed:
        return AgentFileResult(path, "not-found")
    if next_content.strip():
        atomic_write(path, next_content.rstrip() + "\n")
    else:
        path.unlink()
    return AgentFileResult(path, "removed")


codex_lite_target = CodexLiteTarget()
