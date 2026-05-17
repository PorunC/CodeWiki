import hashlib
import re
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlparse

from backend.app.config import get_settings
from backend.app.services.language_detector import LanguageDetector
from backend.app.services.repo_scanner.file_info import scan_file
from backend.app.services.repo_scanner.filesystem import FileSystemWalker
from backend.app.services.repo_scanner.git_ops import GitOperations
from backend.app.services.repo_scanner.models import RepoDescriptor, RepoScanResult

GIT_URL_SCHEMES = {"http", "https", "ssh", "git", "file"}
SCP_LIKE_GIT_URL = re.compile(r"^[A-Za-z0-9_.-]+@[^:]+:.+")


class RepoScanner:
    def __init__(
        self,
        *,
        language_detector: LanguageDetector | None = None,
        max_file_size_bytes: int = 2_000_000,
        storage_dir: Path | str | None = None,
        file_walker: FileSystemWalker | None = None,
        git_operations: GitOperations | None = None,
    ) -> None:
        self.language_detector = language_detector or LanguageDetector()
        self.max_file_size_bytes = max_file_size_bytes
        self.storage_dir = Path(storage_dir) if storage_dir is not None else get_settings().storage_dir
        self.file_walker = file_walker or FileSystemWalker(
            max_file_size_bytes=self.max_file_size_bytes,
        )
        self.git = git_operations or GitOperations()

    def describe(self, path: str, *, name: str | None = None, source_type: str = "local") -> RepoDescriptor:
        requested_path = path.strip()
        if is_git_url(requested_path):
            repo_path = self._ensure_git_clone(requested_path)
            source_type = "git"
            default_name = repo_name_from_git_url(requested_path)
        else:
            repo_path = Path(requested_path).expanduser().resolve()
            default_name = repo_path.name
        if not repo_path.exists():
            raise FileNotFoundError(f"Repository path does not exist: {repo_path}")
        if not repo_path.is_dir():
            raise NotADirectoryError(f"Repository path is not a directory: {repo_path}")
        git_url, commit_hash = self.git.metadata(repo_path)
        return RepoDescriptor(
            id=hashlib.sha1(str(repo_path).encode("utf-8")).hexdigest()[:16],
            name=name or default_name,
            path=str(repo_path),
            source_type=source_type,
            git_url=git_url or (requested_path if is_git_url(requested_path) else None),
            commit_hash=commit_hash,
        )

    def scan(self, path: str, *, name: str | None = None, source_type: str = "local") -> RepoScanResult:
        repo = self.describe(path, name=name, source_type=source_type)
        root = Path(repo.path)
        walk = self.file_walker.walk(root)
        files = [
            scan_file(root, file_path, self.language_detector)
            for file_path in walk.file_paths
        ]

        commit_times = self.git.file_commit_times(root, [file.path for file in files if file.is_source])
        if commit_times:
            files = [
                replace(file, last_commit_at=commit_times.get(file.path))
                for file in files
            ]

        return RepoScanResult(
            repo=repo,
            files=sorted(files, key=lambda item: item.path),
            scanned_count=len(files),
            ignored_count=walk.ignored_count,
            skipped_count=walk.skipped_count,
        )

    def _ensure_git_clone(self, git_url: str) -> Path:
        repo_path = clone_path_for_git_url(git_url, self.storage_dir)
        if repo_path.exists():
            if not repo_path.is_dir():
                raise NotADirectoryError(f"Git clone destination is not a directory: {repo_path}")
            if (repo_path / ".git").exists():
                return repo_path.resolve()
            if any(repo_path.iterdir()):
                raise ValueError(
                    f"Git clone destination exists and is not a repository: {repo_path}"
                )

        return self.git.clone(git_url, repo_path)


def is_git_url(value: str) -> bool:
    text = value.strip()
    if not text:
        return False
    if SCP_LIKE_GIT_URL.match(text):
        return True
    parsed = urlparse(text)
    return parsed.scheme in GIT_URL_SCHEMES and bool(parsed.path) and (
        parsed.scheme == "file" or bool(parsed.netloc)
    )


def clone_path_for_git_url(git_url: str, storage_dir: Path | str) -> Path:
    normalized = normalize_git_url(git_url)
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]
    directory_name = f"{safe_repo_dir_name(repo_name_from_git_url(git_url))}-{digest}"
    return Path(storage_dir).expanduser().resolve() / "repos" / directory_name


def normalize_git_url(git_url: str) -> str:
    return git_url.strip().rstrip("/")


def repo_name_from_git_url(git_url: str) -> str:
    text = normalize_git_url(git_url)
    if SCP_LIKE_GIT_URL.match(text):
        path = text.split(":", 1)[1]
    else:
        path = urlparse(text).path
    repo_name = path.rstrip("/").rsplit("/", 1)[-1]
    if repo_name.endswith(".git"):
        repo_name = repo_name.removesuffix(".git")
    return repo_name or "repository"


def safe_repo_dir_name(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("._-")
    return (safe or "repository")[:80]
