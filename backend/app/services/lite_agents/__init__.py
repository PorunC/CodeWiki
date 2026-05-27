from __future__ import annotations

from pathlib import Path

from backend.app.services.lite_agents.registry import get_target, resolve_agent_targets
from backend.app.services.lite_agents.types import (
    AgentFileResult,
    AgentInstallResult,
    AgentTarget,
    FileAction,
    InstallLocation,
)


def install_lite_agents(
    *,
    targets: list[AgentTarget],
    location: InstallLocation,
    project_path: str | Path = ".",
    auto_allow: bool = True,
    home: str | Path | None = None,
) -> list[AgentInstallResult]:
    project = Path(project_path).expanduser().resolve()
    home_path = Path(home).expanduser().resolve() if home is not None else Path.home()
    return [
        get_target(target).install(
            location=location,
            project=project,
            home=home_path,
            auto_allow=auto_allow,
        )
        for target in targets
    ]


def uninstall_lite_agents(
    *,
    targets: list[AgentTarget],
    location: InstallLocation,
    project_path: str | Path = ".",
    home: str | Path | None = None,
) -> list[AgentInstallResult]:
    project = Path(project_path).expanduser().resolve()
    home_path = Path(home).expanduser().resolve() if home is not None else Path.home()
    return [
        get_target(target).uninstall(
            location=location,
            project=project,
            home=home_path,
        )
        for target in targets
    ]


def print_lite_agent_config(
    *,
    target: AgentTarget,
    location: InstallLocation,
    project_path: str | Path = ".",
    home: str | Path | None = None,
) -> str:
    project = Path(project_path).expanduser().resolve()
    home_path = Path(home).expanduser().resolve() if home is not None else Path.home()
    return get_target(target).print_config(location=location, project=project, home=home_path)


__all__ = [
    "AgentFileResult",
    "AgentInstallResult",
    "AgentTarget",
    "FileAction",
    "InstallLocation",
    "install_lite_agents",
    "print_lite_agent_config",
    "resolve_agent_targets",
    "uninstall_lite_agents",
]
