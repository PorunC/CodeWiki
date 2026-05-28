import hashlib
import re
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlparse

from backend.app.config import get_settings
from backend.app.services.language_detector import LanguageDetector
from backend.app.services.repo_scanner.file_info import modified_at_iso, scan_file, scan_file_metadata
from backend.app.services.repo_scanner.filesystem import FileSystemWalker
from backend.app.services.repo_scanner.git_ops import GitOperations
from backend.app.services.repo_scanner.models import RepoDescriptor, RepoFileScanResult, RepoScanResult

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

    def scan(
        self,
        path: str,
        *,
        name: str | None = None,
        source_type: str = "local",
        known_hashes: Mapping[str, str] | None = None,
        known_file_metadata: Mapping[str, tuple[int | None, str | None]] | None = None,
        hash_paths: set[str] | None = None,
        ) -> RepoScanResult:
        repo = self.describe(path, name=name, source_type=source_type)
        root = Path(repo.path)
        walk = self.file_walker.walk(root)
        files = []
        for file_path in walk.file_paths:
            relative_path = file_path.relative_to(root).as_posix()
            stat = file_path.stat()
            known_sha256 = _known_hash_for(
                relative_path,
                stat_size=stat.st_size,
                modified_at=modified_at_iso(stat),
                known_hashes=known_hashes,
                known_file_metadata=known_file_metadata,
                hash_paths=hash_paths,
            )
            files.append(
                scan_file(
                    root,
                    file_path,
                    self.language_detector,
                    known_sha256=known_sha256,
                    stat=stat,
                )
            )

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

    def scan_files(
        self,
        path: str,
        *,
        name: str | None = None,
        source_type: str = "local",
    ) -> RepoFileScanResult:
        repo = self.describe(path, name=name, source_type=source_type)
        root = Path(repo.path)
        git_files = self.git.list_files(root)
        if git_files is None:
            walk = FileSystemWalker(
                max_file_size_bytes=self.max_file_size_bytes,
                detect_binary=False,
            ).walk(root)
            file_paths = walk.file_paths
            ignored_count = walk.ignored_count
            skipped_count = walk.skipped_count
        else:
            file_paths = []
            skipped_count = 0
            for relative_path in git_files:
                file_path = root / relative_path
                try:
                    stat = file_path.stat()
                except OSError:
                    skipped_count += 1
                    continue
                if not file_path.is_file() or stat.st_size > self.max_file_size_bytes:
                    skipped_count += 1
                    continue
                file_paths.append(file_path)
            ignored_count = 0
        files = [
            scan_file_metadata(
                root,
                file_path,
                self.language_detector,
                stat=file_path.stat(),
            )
            for file_path in file_paths
        ]
        return RepoFileScanResult(
            repo=repo,
            files=sorted(files, key=lambda item: item.path),
            scanned_count=len(files),
            ignored_count=ignored_count,
            skipped_count=skipped_count,
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


def _known_hash_for(
    path: str,
    *,
    stat_size: int,
    modified_at: str,
    known_hashes: Mapping[str, str] | None,
    known_file_metadata: Mapping[str, tuple[int | None, str | None]] | None,
    hash_paths: set[str] | None,
) -> str | None:
    if not known_hashes or path not in known_hashes:
        return None
    if hash_paths is None or path in hash_paths:
        return None
    previous_size, previous_modified_at = (known_file_metadata or {}).get(path, (None, None))
    if previous_size != stat_size or previous_modified_at != modified_at:
        return None
    return known_hashes[path]
