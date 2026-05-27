from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

AgentTarget = Literal["claude", "codex"]
InstallLocation = Literal["global", "local"]
FileAction = Literal["created", "updated", "unchanged", "removed", "not-found", "kept"]


@dataclass(frozen=True)
class AgentFileResult:
    path: Path
    action: FileAction


@dataclass(frozen=True)
class AgentInstallResult:
    target: AgentTarget
    files: list[AgentFileResult]
    notes: list[str]


class LiteAgentTarget(Protocol):
    @property
    def id(self) -> AgentTarget: ...

    def supports_location(self, location: InstallLocation) -> bool: ...

    def detected(self, *, location: InstallLocation, project: Path, home: Path) -> bool: ...

    def install(
        self,
        *,
        location: InstallLocation,
        project: Path,
        home: Path,
        auto_allow: bool,
    ) -> AgentInstallResult: ...

    def uninstall(
        self,
        *,
        location: InstallLocation,
        project: Path,
        home: Path,
    ) -> AgentInstallResult: ...

    def print_config(
        self,
        *,
        location: InstallLocation,
        project: Path,
        home: Path,
    ) -> str: ...
