import re
from typing import Any


def fallback_name_from_payload(item: dict[str, Any]) -> str:
    files = [
        str(file_path)
        for file_path in item.get("files", [])
        if isinstance(file_path, str)
    ]
    labels = [file_label(file_path) for file_path in files]
    labels = [label for label in labels if label and label.lower() not in {"index", "main"}]
    if labels:
        unique = unique_preserve_order(labels)
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


def file_label(file_path: str) -> str:
    file_name = file_path.rsplit("/", 1)[-1]
    if file_name.startswith("__init__."):
        package_name = package_name_from_path(file_path)
        return f"{humanize_name(package_name)} Package" if package_name else "Python Package"
    return humanize_name(file_stem(file_name))


def file_stem(file_name: str) -> str:
    if file_name.startswith("."):
        file_name = file_name.lstrip(".")
    return file_name.rsplit(".", 1)[0]


def package_name_from_path(file_path: str) -> str:
    parts = file_path.split("/")[:-1]
    return parts[-1] if parts else ""


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
