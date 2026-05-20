from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from dotenv import dotenv_values


ENV_KEY_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
ENV_ASSIGNMENT_PATTERN = re.compile(
    r"^(?P<prefix>\s*(?:export\s+)?)"
    r"(?P<key>[A-Za-z_][A-Za-z0-9_]*)"
    r"(?P<separator>\s*=\s*)"
    r".*$"
)
PLAIN_VALUE_PATTERN = re.compile(r"^[A-Za-z0-9_./:@+\-,]*$")

LLM_PROFILES = (
    "default",
    "catalog",
    "community_summary",
    "cluster",
    "page",
    "translation",
    "qa",
    "embedding",
)

COMMON_CONFIG_KEYS = (
    "CODEWIKI_APP_NAME",
    "CODEWIKI_DATABASE_URL",
    "CODEWIKI_STORAGE_DIR",
    "CODEWIKI_LLM__MODE",
    "CODEWIKI_LLM__DEFAULT__MODEL",
    "CODEWIKI_LLM__DEFAULT__PROVIDER_TYPE",
    "CODEWIKI_LLM__DEFAULT__ENDPOINT",
    "CODEWIKI_LLM__DEFAULT__API_KEY",
    "CODEWIKI_LLM__DEFAULT__MAX_TOKENS",
    "CODEWIKI_LLM__TIMEOUT_SECONDS",
    "CODEWIKI_LLM__MAX_RETRIES",
    "CODEWIKI_LLM__CACHE_ENABLED",
    "CODEWIKI_WIKI_BASE_LANGUAGE",
    "CODEWIKI_WIKI_TRANSLATION_LANGUAGES",
)

SECRET_KEY_PARTS = ("API_KEY", "TOKEN", "SECRET", "PASSWORD")


@dataclass(frozen=True)
class EnvAssignment:
    key: str
    value: str


def ensure_env_file(env_file: Path, example_file: Path | None = None) -> bool:
    if env_file.exists():
        return False

    env_file.parent.mkdir(parents=True, exist_ok=True)
    if example_file is not None and example_file.is_file():
        shutil.copyfile(example_file, env_file)
    else:
        env_file.write_text("", encoding="utf-8")
    return True


def read_env_values(env_file: Path) -> dict[str, str]:
    if not env_file.is_file():
        return {}
    values = dotenv_values(env_file)
    return {key: value or "" for key, value in values.items() if key is not None}


def write_env_values(env_file: Path, updates: Mapping[str, str]) -> None:
    normalized_updates = {validate_env_key(key): str(value) for key, value in updates.items()}
    for key, value in normalized_updates.items():
        if "\n" in value or "\r" in value:
            raise ValueError(f"Environment value for {key} cannot contain newlines.")

    env_file.parent.mkdir(parents=True, exist_ok=True)
    lines = env_file.read_text(encoding="utf-8").splitlines(keepends=True) if env_file.exists() else []
    seen: set[str] = set()
    rewritten: list[str] = []

    for raw_line in lines:
        line = raw_line.rstrip("\r\n")
        newline = "\n" if raw_line.endswith(("\n", "\r")) else ""
        match = ENV_ASSIGNMENT_PATTERN.match(line)
        if match and match.group("key") in normalized_updates:
            key = match.group("key")
            rewritten.append(
                f"{match.group('prefix')}{key}{match.group('separator')}"
                f"{format_env_value(normalized_updates[key])}{newline or '\n'}"
            )
            seen.add(key)
            continue
        rewritten.append(raw_line if newline else f"{raw_line}\n")

    missing = [key for key in normalized_updates if key not in seen]
    if missing and rewritten and rewritten[-1].strip():
        rewritten.append("\n")
    for key in missing:
        rewritten.append(f"{key}={format_env_value(normalized_updates[key])}\n")

    env_file.write_text("".join(rewritten), encoding="utf-8")


def parse_env_assignment(raw_assignment: str) -> EnvAssignment:
    if "=" not in raw_assignment:
        raise ValueError(f"Expected KEY=VALUE, got {raw_assignment!r}.")
    key, value = raw_assignment.split("=", 1)
    return EnvAssignment(validate_env_key(key.strip()), value)


def validate_env_key(key: str) -> str:
    if not ENV_KEY_PATTERN.fullmatch(key):
        raise ValueError(f"Invalid environment variable name: {key!r}.")
    return key


def llm_profile_key(profile: str, field: str) -> str:
    normalized_profile = profile.lower().replace("-", "_")
    normalized_field = field.upper()
    if normalized_profile not in LLM_PROFILES:
        raise ValueError(f"Unsupported LLM profile: {profile}")
    if normalized_profile == "default":
        return f"CODEWIKI_LLM__DEFAULT__{normalized_field}"
    return f"CODEWIKI_LLM__PROFILES__{normalized_profile.upper()}__{normalized_field}"


def codewiki_values(values: Mapping[str, str]) -> dict[str, str]:
    common_rank = {key: index for index, key in enumerate(COMMON_CONFIG_KEYS)}
    keys = sorted(
        (key for key in values if key.startswith("CODEWIKI_")),
        key=lambda key: (common_rank.get(key, len(common_rank)), key),
    )
    return {key: values[key] for key in keys}


def mask_config_values(values: Mapping[str, str], *, show_secrets: bool = False) -> dict[str, str]:
    return {key: mask_value(key, value, show_secrets=show_secrets) for key, value in values.items()}


def mask_value(key: str, value: str, *, show_secrets: bool = False) -> str:
    if not value or show_secrets or not is_secret_key(key):
        return value
    return "********"


def is_secret_key(key: str) -> bool:
    return any(part in key.upper() for part in SECRET_KEY_PARTS)


def format_env_value(value: str) -> str:
    if PLAIN_VALUE_PATTERN.fullmatch(value):
        return value
    return json.dumps(value)
