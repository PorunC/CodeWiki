from pathlib import Path


SOURCE_LANGUAGES = {
    "python",
    "typescript",
    "javascript",
    "tsx",
    "jsx",
    "java",
    "go",
    "rust",
    "c",
    "cpp",
    "csharp",
    "kotlin",
    "ruby",
    "php",
    "swift",
}


EXTENSION_LANGUAGE: dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "jsx",
    ".ts": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".tsx": "tsx",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".md": "markdown",
    ".mdx": "mdx",
    ".json": "json",
    ".jsonc": "jsonc",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".ini": "ini",
    ".env": "dotenv",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".sql": "sql",
    ".html": "html",
    ".css": "css",
    ".scss": "scss",
}

FILENAME_LANGUAGE: dict[str, str] = {
    "Dockerfile": "dockerfile",
    "Containerfile": "dockerfile",
    "Makefile": "makefile",
    "Rakefile": "ruby",
    "Gemfile": "ruby",
    "go.mod": "go-mod",
    "go.sum": "go-sum",
    "package.json": "json",
    "tsconfig.json": "jsonc",
    "pyproject.toml": "toml",
    "requirements.txt": "requirements",
}


class LanguageDetector:
    def detect(self, path: Path) -> str:
        if path.name in FILENAME_LANGUAGE:
            return FILENAME_LANGUAGE[path.name]
        if path.suffix in EXTENSION_LANGUAGE:
            return EXTENSION_LANGUAGE[path.suffix]
        if path.name.startswith(".env"):
            return "dotenv"
        return "unknown"

    def is_source_language(self, language: str) -> bool:
        return language in SOURCE_LANGUAGES

