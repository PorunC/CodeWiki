from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from backend.app.services.lite_agents.constants import (
    CLAUDE_LITE_PERMISSIONS,
    CODEWIKI_LITE_INSTRUCTIONS,
    CODEWIKI_LITE_SERVER_NAME,
)
from backend.app.services.lite_agents.io import (
    file_action_for_write,
    read_json,
    remove_json_mcp_entry,
    remove_marked_section,
    write_json,
    write_marked_section,
)
from backend.app.services.lite_agents.mcp import mcp_server_config
from backend.app.services.lite_agents.types import (
    AgentFileResult,
    AgentInstallResult,
    InstallLocation,
)


class ClaudeLiteTarget:
    id: Literal["claude"] = "claude"

    def supports_location(self, location: InstallLocation) -> bool:
        return True

    def detected(self, *, location: InstallLocation, project: Path, home: Path) -> bool:
        return _mcp_path(location=location, project=project, home=home).exists() or _config_dir(
            location,
            project,
            home,
        ).exists()

    def install(
        self,
        *,
        location: InstallLocation,
        project: Path,
        home: Path,
        auto_allow: bool,
    ) -> AgentInstallResult:
        files = [_write_mcp_entry(location=location, project=project, home=home)]
        if location == "local":
            migrated = _cleanup_legacy_local(project)
            if migrated is not None:
                files.append(migrated)
        if auto_allow:
            files.append(_write_permissions(location=location, project=project, home=home))
        files.append(write_marked_section(_instructions_path(location, project, home), CODEWIKI_LITE_INSTRUCTIONS))
        return AgentInstallResult(target="claude", files=files, notes=[])

    def uninstall(
        self,
        *,
        location: InstallLocation,
        project: Path,
        home: Path,
    ) -> AgentInstallResult:
        files = [remove_json_mcp_entry(_mcp_path(location=location, project=project, home=home))]
        if location == "local":
            migrated = _cleanup_legacy_local(project)
            if migrated is not None:
                files.append(migrated)
        files.append(_remove_permissions(_settings_path(location, project, home)))
        files.append(remove_marked_section(_instructions_path(location, project, home)))
        return AgentInstallResult(target="claude", files=files, notes=[])

    def print_config(
        self,
        *,
        location: InstallLocation,
        project: Path,
        home: Path,
    ) -> str:
        path = _mcp_path(location=location, project=project, home=home)
        snippet = {"mcpServers": {CODEWIKI_LITE_SERVER_NAME: mcp_server_config(project)}}
        return f"# Add to {path}\n\n{json.dumps(snippet, indent=2)}\n"


def _config_dir(location: InstallLocation, project: Path, home: Path) -> Path:
    return home / ".claude" if location == "global" else project / ".claude"


def _mcp_path(*, location: InstallLocation, project: Path, home: Path) -> Path:
    return home / ".claude.json" if location == "global" else project / ".mcp.json"


def _settings_path(location: InstallLocation, project: Path, home: Path) -> Path:
    return _config_dir(location, project, home) / "settings.json"


def _instructions_path(location: InstallLocation, project: Path, home: Path) -> Path:
    return _config_dir(location, project, home) / "CLAUDE.md"


def _write_mcp_entry(*, location: InstallLocation, project: Path, home: Path) -> AgentFileResult:
    path = _mcp_path(location=location, project=project, home=home)
    existing = read_json(path)
    before = existing.get("mcpServers", {}).get(CODEWIKI_LITE_SERVER_NAME)
    after = mcp_server_config(project)
    if before == after:
        return AgentFileResult(path, "unchanged")
    action = file_action_for_write(path)
    existing.setdefault("mcpServers", {})[CODEWIKI_LITE_SERVER_NAME] = after
    write_json(path, existing)
    return AgentFileResult(path, action)


def _cleanup_legacy_local(project: Path) -> AgentFileResult | None:
    path = project / ".claude.json"
    if not path.exists():
        return None
    result = remove_json_mcp_entry(path)
    return result if result.action == "removed" else None


def _write_permissions(*, location: InstallLocation, project: Path, home: Path) -> AgentFileResult:
    path = _settings_path(location, project, home)
    settings = read_json(path)
    permissions = settings.setdefault("permissions", {})
    allowed = permissions.setdefault("allow", [])
    if not isinstance(allowed, list):
        allowed = []
        permissions["allow"] = allowed
    before = list(allowed)
    for permission in CLAUDE_LITE_PERMISSIONS:
        if permission not in allowed:
            allowed.append(permission)
    if before == allowed and path.exists():
        return AgentFileResult(path, "unchanged")
    action = file_action_for_write(path)
    write_json(path, settings)
    return AgentFileResult(path, action)


def _remove_permissions(path: Path) -> AgentFileResult:
    settings = read_json(path)
    permissions = settings.get("permissions")
    if not isinstance(permissions, dict):
        return AgentFileResult(path, "not-found")
    allowed = permissions.get("allow")
    if not isinstance(allowed, list):
        return AgentFileResult(path, "not-found")
    next_allowed = [
        permission
        for permission in allowed
        if not isinstance(permission, str) or not permission.startswith("mcp__codewiki-lite__")
    ]
    if len(next_allowed) == len(allowed):
        return AgentFileResult(path, "not-found")
    if next_allowed:
        permissions["allow"] = next_allowed
    else:
        permissions.pop("allow", None)
    if not permissions:
        settings.pop("permissions", None)
    if settings:
        write_json(path, settings)
    elif path.exists():
        path.unlink()
    return AgentFileResult(path, "removed")


claude_lite_target = ClaudeLiteTarget()
