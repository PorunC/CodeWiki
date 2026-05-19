from __future__ import annotations

import json
from typing import Any

from backend.app.mcp_server.types import JsonObject
from backend.app.mcp_server.utils import jsonable

DEFAULT_PROTOCOL_VERSION = "2024-11-05"


def params(message: JsonObject) -> JsonObject:
    value = message.get("params") or {}
    if not isinstance(value, dict):
        raise ValueError("JSON-RPC params must be an object.")
    return value


def tool_response(payload: Any, *, is_error: bool = False) -> JsonObject:
    text = payload if isinstance(payload, str) else json.dumps(jsonable(payload), indent=2)
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def result(request_id: Any, payload: Any) -> JsonObject:
    return {"jsonrpc": "2.0", "id": request_id, "result": payload}


def error(request_id: Any, code: int, message: str) -> JsonObject:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}
