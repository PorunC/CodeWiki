import re
from typing import Any


def fallback_name_from_payload(item: dict[str, Any]) -> str:
    files = [
        str(file_path)
        for file_path in item.get("files", [])
        if isinstance(file_path, str)
    ]
    stems = [
        humanize_name(file_path.rsplit("/", 1)[-1].rsplit(".", 1)[0])
        for file_path in files
        if not file_path.rsplit("/", 1)[-1].startswith("__init__")
    ]
    stems = [stem for stem in stems if stem and stem.lower() not in {"index", "main"}]
    if stems:
        unique = unique_preserve_order(stems)
        if len(unique) == 1:
            return unique[0]
        return f"{unique[0]} and {unique[1]}"

    symbols = item.get("symbols", [])
    if isinstance(symbols, list):
        for symbol in symbols:
            if not isinstance(symbol, dict):
                continue
            name = str(symbol.get("name") or "")
            if name and not name.startswith("_"):
                return humanize_name(name)
    current = str(item.get("current_name") or "").strip()
    return current or "Subsystem"


def humanize_name(value: str) -> str:
    value = re.sub(r"^test_", "", value)
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
    value = value.replace("_", " ").replace("-", " ").strip()
    return " ".join(word if word.isupper() else word.capitalize() for word in value.split())


def unique_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(value)
    return unique
