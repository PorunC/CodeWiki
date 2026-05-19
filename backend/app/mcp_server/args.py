from __future__ import annotations

from backend.app.mcp_server.types import JsonObject


def required_string(args: JsonObject, key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Argument '{key}' must be a non-empty string.")
    return value.strip()


def optional_string(args: JsonObject, key: str) -> str | None:
    value = args.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"Argument '{key}' must be a string.")
    return value.strip() or None


def int_arg(args: JsonObject, key: str, default: int) -> int:
    value = args.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Argument '{key}' must be an integer.")
    return value


def bool_arg(args: JsonObject, key: str, default: bool) -> bool:
    value = args.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"Argument '{key}' must be a boolean.")
    return value


def optional_list(args: JsonObject, key: str) -> list[str] | None:
    value = args.get(key)
    if value is None:
        return None
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return value
    raise ValueError(f"Argument '{key}' must be a string or list of strings.")


def string_list_arg(args: JsonObject, key: str) -> list[str]:
    value = args.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"Argument '{key}' must be a list of strings.")
    return value
