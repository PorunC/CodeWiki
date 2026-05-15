import json
import re
from typing import Any

from backend.app.services.prompts import load_prompt


def _page_messages(
    prompt: str,
    user_payload: dict[str, Any],
    validation_errors: list[str],
) -> list[dict[str, str]]:
    instruction = (
        "Return only a JSON object. Do not include Mermaid blocks; the server "
        "will generate abstract diagrams from validated graph facts. source_refs must "
        "be selected from allowed_source_refs. Use [[S#]] citation markers only "
        "for source refs you return. Use catalog_context.related_pages only for "
        "real related-page mentions; do not invent wiki pages or links."
    )
    if validation_errors:
        instruction = (
            f"{instruction}\nRepair the previous response. Validation errors: "
            f"{json.dumps(validation_errors, ensure_ascii=False)}"
        )
    return [
        {"role": "system", "content": prompt},
        {
            "role": "user",
            "content": f"{instruction}\n{json.dumps(user_payload, ensure_ascii=False)}",
        },
    ]


def _catalog_messages(
    prompt: str,
    user_payload: dict[str, Any],
    validation_errors: list[str],
) -> list[dict[str, str]]:
    instruction = (
        "Return only a valid JSON object. The object must contain `title` and `items`; "
        "`items` must be an array of catalog items. Do not include Markdown fences, "
        "comments, trailing commas, or prose outside JSON."
    )
    if validation_errors:
        instruction = (
            f"{instruction}\nRepair the previous response. Validation errors: "
            f"{json.dumps(validation_errors, ensure_ascii=False)}"
        )
    return [
        {"role": "system", "content": prompt},
        {
            "role": "user",
            "content": f"{instruction}\n{json.dumps(user_payload, ensure_ascii=False)}",
        },
    ]


def _load_prompt(name: str) -> str:
    return load_prompt(name)


def _json_object(content: str) -> dict[str, Any]:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if not match:
            raise ValueError("LLM did not return a JSON object.") from exc
        try:
            payload = json.loads(match.group(0))
        except json.JSONDecodeError as nested_exc:
            raise ValueError(
                f"LLM returned malformed JSON: {nested_exc.msg} at line {nested_exc.lineno}, "
                f"column {nested_exc.colno}."
            ) from nested_exc
    if not isinstance(payload, dict):
        raise ValueError("LLM response must be a JSON object.")
    return payload
