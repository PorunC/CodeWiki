from __future__ import annotations

from pathlib import Path

from backend.app.services.lite_agents.targets import claude_lite_target, codex_lite_target
from backend.app.services.lite_agents.types import AgentTarget, InstallLocation, LiteAgentTarget

TARGETS: dict[AgentTarget, LiteAgentTarget] = {
    "claude": claude_lite_target,
    "codex": codex_lite_target,
}


def get_target(target: AgentTarget) -> LiteAgentTarget:
    return TARGETS[target]


def resolve_agent_targets(
    value: str,
    *,
    location: InstallLocation,
    home: str | Path | None = None,
    project_path: str | Path = ".",
) -> list[AgentTarget]:
    value = value.strip().lower()
    if value == "none":
        return []
    if value == "all":
        requested = list(TARGETS)
    elif value == "auto":
        requested = _auto_detect(location=location, home=home, project_path=project_path)
    else:
        requested = _parse_target_list(value)

    return [target for target in requested if TARGETS[target].supports_location(location)]


def _auto_detect(
    *,
    location: InstallLocation,
    home: str | Path | None,
    project_path: str | Path,
) -> list[AgentTarget]:
    home_path = Path(home).expanduser().resolve() if home is not None else Path.home()
    project = Path(project_path).expanduser().resolve()
    detected = [
        target_id
        for target_id, target in TARGETS.items()
        if target.supports_location(location)
        and target.detected(location=location, project=project, home=home_path)
    ]
    return detected or ["claude"]


def _parse_target_list(value: str) -> list[AgentTarget]:
    requested: list[AgentTarget] = []
    for item in value.split(","):
        target = item.strip()
        if target not in TARGETS:
            raise ValueError("Unknown --target value. Use claude, codex, all, auto, or none.")
        requested.append(target)
    return requested
