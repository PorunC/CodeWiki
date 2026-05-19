from __future__ import annotations

from backend.app.database import SQLiteStore, get_store
from backend.app.mcp_server.protocol import (
    DEFAULT_PROTOCOL_VERSION,
    error,
    params,
    result,
    tool_response,
)
from backend.app.mcp_server.tools import build_tools
from backend.app.mcp_server.types import JsonObject, ToolSpec
from backend.app.mcp_server.utils import package_version


class CodeWikiMCPServer:
    """Small stdio MCP server exposing CodeWiki workflows as tools."""

    def __init__(self, *, store: SQLiteStore | None = None) -> None:
        self.store = store or get_store()
        self.tools: dict[str, ToolSpec] = build_tools(self.store)

    async def handle_message(self, message: JsonObject) -> JsonObject | None:
        method = message.get("method")
        request_id = message.get("id")
        is_notification = "id" not in message
        try:
            if method == "initialize":
                return result(request_id, self._initialize_result(message.get("params")))
            if method in {"notifications/initialized", "initialized"}:
                return None
            if isinstance(method, str) and method.startswith("notifications/"):
                return None
            if method == "ping":
                return result(request_id, {})
            if method == "tools/list":
                return result(request_id, {"tools": [tool.payload() for tool in self.tools.values()]})
            if method == "tools/call":
                return result(request_id, await self._call_tool(params(message)))
            if method == "resources/list":
                return result(request_id, {"resources": []})
            if method == "prompts/list":
                return result(request_id, {"prompts": []})
            if method == "logging/setLevel":
                return result(request_id, {})
            if method in {"shutdown", "exit"}:
                return None if is_notification else result(request_id, {})
        except Exception as exc:
            if is_notification:
                return None
            return error(request_id, -32603, str(exc))
        if is_notification:
            return None
        return error(request_id, -32601, f"Method not found: {method}")

    def _initialize_result(self, raw_params: object) -> JsonObject:
        protocol_version = DEFAULT_PROTOCOL_VERSION
        if isinstance(raw_params, dict) and isinstance(raw_params.get("protocolVersion"), str):
            protocol_version = raw_params["protocolVersion"]
        return {
            "protocolVersion": protocol_version,
            "capabilities": {"tools": {}},
            "serverInfo": {
                "name": "codewiki",
                "version": package_version(),
            },
        }

    async def _call_tool(self, call_params: JsonObject) -> JsonObject:
        name = call_params.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError("tools/call requires a tool name.")
        tool = self.tools.get(name)
        if tool is None:
            raise ValueError(f"Unknown tool: {name}")
        arguments = call_params.get("arguments") or {}
        if not isinstance(arguments, dict):
            raise ValueError("Tool arguments must be an object.")
        try:
            payload = await tool.handler(arguments)
        except Exception as exc:
            return tool_response({"error": str(exc)}, is_error=True)
        return tool_response(payload)
