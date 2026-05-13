from dataclasses import dataclass
from pathlib import Path

from pathspec.patterns.gitignore.spec import GitIgnoreSpecPattern


DEFAULT_IGNORE_PATTERNS = [
    ".git/",
    ".hg/",
    ".svn/",
    ".idea/",
    ".vscode/",
    ".env",
    ".env.*",
    "__pycache__/",
    ".pytest_cache/",
    ".ruff_cache/",
    ".mypy_cache/",
    ".venv/",
    "venv/",
    "node_modules/",
    "dist/",
    "build/",
    "coverage/",
    ".next/",
    ".nuxt/",
    ".turbo/",
    "target/",
    "*.pyc",
    "*.pyo",
    "*.so",
    "*.dylib",
    "*.dll",
    "*.exe",
    "*.class",
    "*.jar",
    "*.zip",
    "*.tar",
    "*.gz",
    "*.png",
    "*.jpg",
    "*.jpeg",
    "*.gif",
    "*.webp",
    "*.ico",
    "*.pdf",
]


@dataclass(frozen=True)
class IgnorePattern:
    base_path: Path
    pattern: GitIgnoreSpecPattern


class IgnoreMatcher:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._patterns: list[IgnorePattern] = []
        self.add_lines(root, DEFAULT_IGNORE_PATTERNS)

    def add_gitignore(self, directory: Path) -> None:
        gitignore_path = directory / ".gitignore"
        if not gitignore_path.is_file():
            return
        self.add_lines(directory, gitignore_path.read_text(encoding="utf-8", errors="replace").splitlines())

    def add_lines(self, base_path: Path, lines: list[str]) -> None:
        for raw_line in lines:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            self._patterns.append(IgnorePattern(base_path=base_path, pattern=GitIgnoreSpecPattern(line)))

    def is_ignored(self, path: Path, *, is_dir: bool) -> bool:
        ignored = False
        for entry in self._patterns:
            try:
                relative = path.relative_to(entry.base_path).as_posix()
            except ValueError:
                continue
            if not relative:
                continue

            candidates = [relative]
            if is_dir and not relative.endswith("/"):
                candidates.append(f"{relative}/")

            if any(entry.pattern.match_file(candidate) for candidate in candidates):
                ignored = bool(entry.pattern.include)
        return ignored
