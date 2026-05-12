import hashlib
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pathspec.patterns.gitignore.spec import GitIgnoreSpecPattern

from backend.app.services.language_detector import LanguageDetector


DEFAULT_IGNORE_PATTERNS = [
    ".git/",
    ".hg/",
    ".svn/",
    ".idea/",
    ".vscode/",
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
class RepoDescriptor:
    id: str
    name: str
    path: str
    source_type: str
    git_url: str | None = None
    commit_hash: str | None = None


@dataclass(frozen=True)
class ScannedFile:
    path: str
    absolute_path: str
    language: str
    is_source: bool
    size_bytes: int
    sha256: str
    modified_at: str


@dataclass(frozen=True)
class RepoScanResult:
    repo: RepoDescriptor
    files: list[ScannedFile]
    scanned_count: int
    ignored_count: int
    skipped_count: int


@dataclass(frozen=True)
class _IgnorePattern:
    base_path: Path
    pattern: GitIgnoreSpecPattern


class IgnoreMatcher:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._patterns: list[_IgnorePattern] = []
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
            self._patterns.append(_IgnorePattern(base_path=base_path, pattern=GitIgnoreSpecPattern(line)))

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


class RepoScanner:
    def __init__(
        self,
        *,
        language_detector: LanguageDetector | None = None,
        max_file_size_bytes: int = 2_000_000,
    ) -> None:
        self.language_detector = language_detector or LanguageDetector()
        self.max_file_size_bytes = max_file_size_bytes

    def describe(self, path: str, *, name: str | None = None, source_type: str = "local") -> RepoDescriptor:
        repo_path = Path(path).expanduser().resolve()
        if not repo_path.exists():
            raise FileNotFoundError(f"Repository path does not exist: {repo_path}")
        if not repo_path.is_dir():
            raise NotADirectoryError(f"Repository path is not a directory: {repo_path}")
        git_url, commit_hash = _git_metadata(repo_path)
        return RepoDescriptor(
            id=hashlib.sha1(str(repo_path).encode("utf-8")).hexdigest()[:16],
            name=name or repo_path.name,
            path=str(repo_path),
            source_type=source_type,
            git_url=git_url,
            commit_hash=commit_hash,
        )

    def scan(self, path: str, *, name: str | None = None, source_type: str = "local") -> RepoScanResult:
        repo = self.describe(path, name=name, source_type=source_type)
        root = Path(repo.path)
        matcher = IgnoreMatcher(root)
        files: list[ScannedFile] = []
        ignored_count = 0
        skipped_count = 0

        for current_root, dir_names, file_names in os.walk(root, topdown=True, followlinks=False):
            current_path = Path(current_root)
            if matcher.is_ignored(current_path, is_dir=True):
                ignored_count += 1
                dir_names[:] = []
                continue

            matcher.add_gitignore(current_path)

            kept_dirs: list[str] = []
            for dir_name in dir_names:
                dir_path = current_path / dir_name
                if dir_path.is_symlink() or matcher.is_ignored(dir_path, is_dir=True):
                    ignored_count += 1
                    continue
                kept_dirs.append(dir_name)
            dir_names[:] = kept_dirs

            for file_name in file_names:
                file_path = current_path / file_name
                if file_path.is_symlink() or matcher.is_ignored(file_path, is_dir=False):
                    ignored_count += 1
                    continue
                if not file_path.is_file():
                    skipped_count += 1
                    continue
                if file_path.stat().st_size > self.max_file_size_bytes or self._is_probably_binary(file_path):
                    skipped_count += 1
                    continue
                files.append(self._scan_file(root, file_path))

        return RepoScanResult(
            repo=repo,
            files=sorted(files, key=lambda item: item.path),
            scanned_count=len(files),
            ignored_count=ignored_count,
            skipped_count=skipped_count,
        )

    def _scan_file(self, root: Path, file_path: Path) -> ScannedFile:
        stat = file_path.stat()
        language = self.language_detector.detect(file_path)
        return ScannedFile(
            path=file_path.relative_to(root).as_posix(),
            absolute_path=str(file_path),
            language=language,
            is_source=self.language_detector.is_source_language(language),
            size_bytes=stat.st_size,
            sha256=self._sha256(file_path),
            modified_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
        )

    def _sha256(self, file_path: Path) -> str:
        digest = hashlib.sha256()
        with file_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _is_probably_binary(self, file_path: Path) -> bool:
        with file_path.open("rb") as handle:
            sample = handle.read(4096)
        return b"\0" in sample


def _git_metadata(repo_path: Path) -> tuple[str | None, str | None]:
    git_dir = repo_path / ".git"
    if not git_dir.is_dir():
        return None, None
    return _git_origin_url(git_dir), _git_head_commit(git_dir)


def _git_origin_url(git_dir: Path) -> str | None:
    config_path = git_dir / "config"
    if not config_path.is_file():
        return None
    current_section = ""
    for raw_line in config_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            current_section = line
            continue
        if current_section == '[remote "origin"]' and line.startswith("url"):
            _, _, value = line.partition("=")
            return value.strip() or None
    return None


def _git_head_commit(git_dir: Path) -> str | None:
    head_path = git_dir / "HEAD"
    if not head_path.is_file():
        return None
    head = head_path.read_text(encoding="utf-8", errors="replace").strip()
    if not head:
        return None
    if not head.startswith("ref:"):
        return head
    ref_name = head.removeprefix("ref:").strip()
    ref_path = git_dir / ref_name
    if ref_path.is_file():
        return ref_path.read_text(encoding="utf-8", errors="replace").strip() or None
    packed_refs = git_dir / "packed-refs"
    if packed_refs.is_file():
        for raw_line in packed_refs.read_text(encoding="utf-8", errors="replace").splitlines():
            if raw_line.startswith("#") or not raw_line.strip():
                continue
            commit, _, ref = raw_line.partition(" ")
            if ref.strip() == ref_name:
                return commit.strip() or None
    return None
