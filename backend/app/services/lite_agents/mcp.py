from __future__ import annotations

from pathlib import Path
from typing import Any


def mcp_server_config(project: Path) -> dict[str, Any]:
    return {
        "type": "stdio",
        "command": "codewiki",
        "args": ["mcp", "--lite", "--path", str(project)],
    }
