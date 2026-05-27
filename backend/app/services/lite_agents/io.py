from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

from backend.app.services.lite_agents.constants import (
    CODEWIKI_LITE_SECTION_END,
    CODEWIKI_LITE_SECTION_START,
    CODEWIKI_LITE_SERVER_NAME,
)
from backend.app.services.lite_agents.types import AgentFileResult, FileAction


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        backup = path.with_name(path.name + ".backup")
        shutil.copyfile(path, backup)
        return {}
    return payload if isinstance(payload, dict) else {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    atomic_write(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    try:
        tmp_path.write_text(content, encoding="utf-8")
        tmp_path.replace(path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def write_marked_section(path: Path, body: str) -> AgentFileResult:
    if not path.exists():
        atomic_write(path, body + "\n")
        return AgentFileResult(path, "created")
    existing = read_text(path)
    start = existing.find(CODEWIKI_LITE_SECTION_START)
    end = existing.find(CODEWIKI_LITE_SECTION_END)
    if start != -1 and end > start:
        existing_block = existing[start : end + len(CODEWIKI_LITE_SECTION_END)]
        if existing_block == body:
            return AgentFileResult(path, "unchanged")
        next_content = existing[:start] + body + existing[end + len(CODEWIKI_LITE_SECTION_END) :]
        atomic_write(path, next_content)
        return AgentFileResult(path, "updated")
    separator = "\n\n" if existing.strip() else ""
    atomic_write(path, existing.rstrip() + separator + body + "\n")
    return AgentFileResult(path, "updated")


def remove_marked_section(path: Path) -> AgentFileResult:
    if not path.exists():
        return AgentFileResult(path, "kept")
    existing = read_text(path)
    start = existing.find(CODEWIKI_LITE_SECTION_START)
    end = existing.find(CODEWIKI_LITE_SECTION_END)
    if start == -1 or end <= start:
        return AgentFileResult(path, "not-found")
    before = existing[:start].rstrip()
    after = existing[end + len(CODEWIKI_LITE_SECTION_END) :].lstrip()
    next_content = before + ("\n\n" if before and after else "") + after
    if next_content.strip():
        atomic_write(path, next_content.rstrip() + "\n")
    else:
        path.unlink()
    return AgentFileResult(path, "removed")


def upsert_toml_table(content: str, header: str, block: str) -> tuple[str, bool]:
    start, end = _find_toml_table(content, header)
    if start is None:
        separator = "\n\n" if content.strip() else ""
        return content.rstrip() + separator + block + "\n", True
    existing = content[start:end].strip()
    if existing == block.strip():
        return content, False
    return content[:start] + block + "\n" + content[end:].lstrip("\n"), True


def remove_toml_table(content: str, header: str) -> tuple[str, bool]:
    start, end = _find_toml_table(content, header)
    if start is None:
        return content, False
    return (content[:start].rstrip() + "\n\n" + content[end:].lstrip()).strip() + "\n", True


def remove_json_mcp_entry(path: Path) -> AgentFileResult:
    existing = read_json(path)
    servers = existing.get("mcpServers")
    if not isinstance(servers, dict) or CODEWIKI_LITE_SERVER_NAME not in servers:
        return AgentFileResult(path, "not-found")
    del servers[CODEWIKI_LITE_SERVER_NAME]
    if not servers:
        existing.pop("mcpServers", None)
    if existing:
        write_json(path, existing)
    elif path.exists():
        path.unlink()
    return AgentFileResult(path, "removed")


def file_action_for_write(path: Path) -> FileAction:
    return "created" if not path.exists() else "updated"


def _find_toml_table(content: str, header: str) -> tuple[int | None, int | None]:
    lines = content.splitlines(keepends=True)
    offset = 0
    start: int | None = None
    end = len(content)
    target = f"[{header}]"
    for line in lines:
        stripped = line.strip()
        if stripped == target:
            start = offset
        elif start is not None and stripped.startswith("[") and stripped.endswith("]"):
            end = offset
            break
        offset += len(line)
    return start, end if start is not None else None
