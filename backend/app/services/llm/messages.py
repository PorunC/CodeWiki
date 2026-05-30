import json
from typing import Any


def stable_json_message(
    label: str,
    payload: Any,
    *,
    sort_keys: bool = True,
) -> dict[str, str]:
    return {
        "role": "user",
        "content": f"{label}:\n{json_payload(payload, sort_keys=sort_keys)}",
    }


def dynamic_json_message(label: str, payload: Any) -> dict[str, str]:
    return {
        "role": "user",
        "content": f"{label}:\n{json_payload(payload, sort_keys=False)}",
    }


def json_payload(payload: Any, *, sort_keys: bool = False) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=sort_keys,
    )
