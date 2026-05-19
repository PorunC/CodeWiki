from __future__ import annotations

import asyncio
import json
import sys

from backend.app.mcp_server.protocol import error
from backend.app.mcp_server.server import CodeWikiMCPServer


async def run_stdio(server: CodeWikiMCPServer | None = None) -> None:
    server = server or CodeWikiMCPServer()
    for raw_line in sys.stdin.buffer:
        line = raw_line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
            if not isinstance(message, dict):
                response = error(None, -32600, "Invalid JSON-RPC request.")
            else:
                response = await server.handle_message(message)
        except json.JSONDecodeError as exc:
            response = error(None, -32700, f"Parse error: {exc}")
        if response is None:
            continue
        sys.stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
        sys.stdout.flush()


def main() -> None:
    asyncio.run(run_stdio())
