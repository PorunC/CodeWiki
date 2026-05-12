from dataclasses import dataclass, field
from pathlib import Path


DEFAULT_EXCLUDED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".idea",
    ".vscode",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    "coverage",
    ".next",
    ".nuxt",
    ".turbo",
    "target",
    "out",
    ".output",
}

README_NAMES = ("README.md", "README.MD", "readme.md", "README.rst", "README.txt", "README")
COMMON_KEY_FILES = (
    "README.md",
    "pyproject.toml",
    "package.json",
    "tsconfig.json",
    "vite.config.ts",
    "next.config.ts",
    "requirements.txt",
    "Dockerfile",
    "docker-compose.yml",
    "compose.yaml",
    "Makefile",
    ".env.example",
)


@dataclass(frozen=True)
class RepositoryContext:
    project_type: str
    directory_tree: str
    readme_content: str
    key_files: list[str] = field(default_factory=list)
    entry_points: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "project_type": self.project_type,
            "directory_tree_format": "compact",
            "directory_tree": self.directory_tree,
            "readme_content": self.readme_content,
            "key_files": self.key_files,
            "entry_points": self.entry_points,
        }


class RepositoryContextBuilder:
    def __init__(
        self,
        *,
        max_tree_depth: int = 3,
        max_readme_chars: int = 6000,
        max_entries_per_dir: int = 80,
    ) -> None:
        self.max_tree_depth = max_tree_depth
        self.max_readme_chars = max_readme_chars
        self.max_entries_per_dir = max_entries_per_dir

    def build(self, repo_path: str) -> RepositoryContext:
        root = Path(repo_path).resolve()
        return RepositoryContext(
            project_type=_detect_project_type(root),
            directory_tree=self._directory_tree(root),
            readme_content=self._readme(root),
            key_files=_key_files(root),
            entry_points=_entry_points(root),
        )

    def _directory_tree(self, root: Path) -> str:
        lines = [root.name]
        self._append_tree(root, lines, depth=0)
        return "\n".join(lines)

    def _append_tree(self, directory: Path, lines: list[str], *, depth: int) -> None:
        if depth >= self.max_tree_depth:
            return
        try:
            entries = sorted(
                [
                    entry
                    for entry in directory.iterdir()
                    if not entry.name.startswith(".") and entry.name not in DEFAULT_EXCLUDED_DIRS
                ],
                key=lambda entry: (entry.is_file(), entry.name.lower()),
            )[: self.max_entries_per_dir]
        except OSError:
            return

        for entry in entries:
            relative = entry.relative_to(directory)
            suffix = "/" if entry.is_dir() else ""
            lines.append(f"{'  ' * (depth + 1)}- {relative.as_posix()}{suffix}")
            if entry.is_dir():
                self._append_tree(entry, lines, depth=depth + 1)

    def _readme(self, root: Path) -> str:
        for name in README_NAMES:
            path = root / name
            if not path.is_file():
                continue
            content = path.read_text(encoding="utf-8", errors="replace").strip()
            if len(content) > self.max_readme_chars:
                return content[: self.max_readme_chars].rstrip() + "\n\n[README truncated]"
            return content
        return ""


def _detect_project_type(root: Path) -> str:
    types: list[str] = []
    if (root / "pyproject.toml").is_file() or (root / "requirements.txt").is_file():
        types.append("python")
    package_files = [
        path
        for path in root.glob("**/package.json")
        if not _is_in_excluded_dir(path.relative_to(root))
    ][:5]
    if package_files:
        package_text = "\n".join(
            path.read_text(encoding="utf-8", errors="replace") for path in package_files
        )
        if any(marker in package_text for marker in ('"react"', '"next"', '"vite"', '"vue"', '"angular"')):
            types.append("frontend")
        else:
            types.append("nodejs")
    if any(root.glob("*.sln")) or any(root.glob("**/*.csproj")):
        types.append("dotnet")
    if (root / "go.mod").is_file():
        types.append("go")
    if (root / "Cargo.toml").is_file():
        types.append("rust")
    if (root / "pom.xml").is_file() or any(root.glob("build.gradle*")):
        types.append("java")
    if not types:
        return "unknown"
    return "fullstack:" + "+".join(types) if len(types) > 1 else types[0]


def _key_files(root: Path) -> list[str]:
    paths = [name for name in COMMON_KEY_FILES if (root / name).is_file()]
    paths.extend(path.relative_to(root).as_posix() for path in root.glob("*.sln"))
    paths.extend(path.relative_to(root).as_posix() for path in root.glob("*.csproj"))
    return sorted(dict.fromkeys(paths))


def _entry_points(root: Path) -> list[str]:
    patterns = (
        "backend/app/main.py",
        "app.py",
        "main.py",
        "__main__.py",
        "manage.py",
        "frontend/src/main.tsx",
        "frontend/src/main.ts",
        "src/main.tsx",
        "src/main.ts",
        "src/App.tsx",
        "src/App.vue",
        "Program.cs",
        "Startup.cs",
        "cmd/*/main.go",
    )
    entries: list[str] = []
    for pattern in patterns:
        matches = root.glob(pattern)
        entries.extend(
            path.relative_to(root).as_posix()
            for path in matches
            if path.is_file() and not _is_in_excluded_dir(path.relative_to(root))
        )
    return sorted(dict.fromkeys(entries))[:12]


def _is_in_excluded_dir(relative_path: Path) -> bool:
    return any(part in DEFAULT_EXCLUDED_DIRS for part in relative_path.parts)
