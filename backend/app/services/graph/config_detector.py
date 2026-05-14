from dataclasses import dataclass
from pathlib import PurePosixPath

from backend.app.services.repo_scanner import ScannedFile


CONFIG_LANGUAGES = {
    "dotenv",
    "dockerfile",
    "go-mod",
    "ini",
    "json",
    "jsonc",
    "makefile",
    "requirements",
    "toml",
    "yaml",
}
CONFIG_SOURCE_FILENAMES = {
    "config",
    "settings",
    "configuration",
}
CONFIG_SOURCE_SUFFIXES = {
    ".config.js",
    ".config.cjs",
    ".config.mjs",
    ".config.ts",
    ".config.mts",
    ".config.cts",
}
CONFIG_FILENAMES = {
    ".babelrc",
    ".dockerignore",
    ".editorconfig",
    ".env",
    ".env.example",
    ".env.local",
    ".eslintrc",
    ".eslintrc.cjs",
    ".eslintrc.js",
    ".eslintrc.json",
    ".gitignore",
    ".npmrc",
    ".prettierrc",
    ".prettierrc.json",
    "alembic.ini",
    "compose.yaml",
    "compose.yml",
    "docker-compose.yaml",
    "docker-compose.yml",
    "Dockerfile",
    "eslint.config.js",
    "eslint.config.mjs",
    "go.mod",
    "go.sum",
    "jest.config.js",
    "Makefile",
    "mypy.ini",
    "next.config.js",
    "package.json",
    "postcss.config.js",
    "pyproject.toml",
    "pytest.ini",
    "requirements.txt",
    "rollup.config.js",
    "ruff.toml",
    "setup.cfg",
    "tailwind.config.js",
    "tox.ini",
    "tsconfig.json",
    "vite.config.ts",
    "webpack.config.js",
}
NORMALIZED_CONFIG_FILENAMES = {name.lower() for name in CONFIG_FILENAMES}
CONFIG_DIRECTORIES = {"config", "configs", "configuration", "settings"}
CONFIG_REFERENCE_TERMS = {
    "config",
    "configuration",
    "dotenv",
    "env",
    "environment",
    "getenv",
    "get_settings",
    "load_dotenv",
    "process",
    "settings",
}


@dataclass(frozen=True)
class ConfigDetection:
    is_config: bool
    kind: str | None = None
    reason: str | None = None
    confidence: float = 0.0


def detect_config_file(file: ScannedFile) -> ConfigDetection:
    path = PurePosixPath(file.path)
    name = path.name
    lower_name = name.lower()
    stem = path.stem.lower()
    suffix = "".join(path.suffixes).lower()
    parts = {part.lower() for part in path.parts[:-1]}

    if name in CONFIG_FILENAMES or lower_name in NORMALIZED_CONFIG_FILENAMES:
        return ConfigDetection(True, kind=config_kind(lower_name, file.language), reason="known_filename", confidence=1.0)
    if lower_name.startswith(".env"):
        return ConfigDetection(True, kind="environment", reason="env_filename", confidence=1.0)
    if any(lower_name.endswith(config_suffix) for config_suffix in CONFIG_SOURCE_SUFFIXES):
        return ConfigDetection(True, kind="tooling", reason="config_suffix", confidence=0.95)
    if stem in CONFIG_SOURCE_FILENAMES and file.language in CONFIG_LANGUAGES | {"python", "javascript", "typescript"}:
        return ConfigDetection(True, kind=config_kind(lower_name, file.language), reason="config_stem", confidence=0.9)
    if parts & CONFIG_DIRECTORIES and file.language in CONFIG_LANGUAGES:
        return ConfigDetection(True, kind=config_kind(lower_name, file.language), reason="config_directory", confidence=0.85)
    if ("config" in lower_name or "settings" in lower_name) and (
        file.language in CONFIG_LANGUAGES or suffix in CONFIG_SOURCE_SUFFIXES
    ):
        return ConfigDetection(True, kind=config_kind(lower_name, file.language), reason="name_heuristic", confidence=0.8)
    return ConfigDetection(False)


def is_config_reference(value: str) -> bool:
    normalized = value.replace("\\", "/").lower()
    parts = {part for part in normalized.replace(".", "/").replace("-", "_").split("/") if part}
    return bool(parts & CONFIG_REFERENCE_TERMS) or any(term in normalized for term in CONFIG_REFERENCE_TERMS)


def config_kind(name: str, language: str) -> str:
    lower = name.lower()
    if lower.startswith(".env") or language == "dotenv":
        return "environment"
    if lower in {"package.json", "go.mod", "go.sum", "requirements.txt", "pyproject.toml"}:
        return "package_manifest"
    if lower.startswith(("docker", "compose")) or language in {"dockerfile", "makefile"}:
        return "build"
    if any(tool in lower for tool in ("eslint", "prettier", "ruff", "mypy", "pytest", "tox")):
        return "tooling"
    return "runtime"
