import hashlib
import os
from dataclasses import replace
from pathlib import Path

from backend.app.services.language_detector import LanguageDetector
from backend.app.services.repo_scanner.file_info import is_probably_binary, scan_file
from backend.app.services.repo_scanner.git import git_file_commit_times, git_metadata
from backend.app.services.repo_scanner.ignore import IgnoreMatcher
from backend.app.services.repo_scanner.models import RepoDescriptor, RepoScanResult, ScannedFile


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
        git_url, commit_hash = git_metadata(repo_path)
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
                if file_path.stat().st_size > self.max_file_size_bytes or is_probably_binary(file_path):
                    skipped_count += 1
                    continue
                files.append(scan_file(root, file_path, self.language_detector))

        commit_times = git_file_commit_times(root, [file.path for file in files if file.is_source])
        if commit_times:
            files = [
                replace(file, last_commit_at=commit_times.get(file.path))
                for file in files
            ]

        return RepoScanResult(
            repo=repo,
            files=sorted(files, key=lambda item: item.path),
            scanned_count=len(files),
            ignored_count=ignored_count,
            skipped_count=skipped_count,
        )

    def _scan_file(self, root: Path, file_path: Path) -> ScannedFile:
        return scan_file(root, file_path, self.language_detector)

    def _sha256(self, file_path: Path) -> str:
        from backend.app.services.repo_scanner.file_info import sha256_file

        return sha256_file(file_path)

    def _is_probably_binary(self, file_path: Path) -> bool:
        return is_probably_binary(file_path)
