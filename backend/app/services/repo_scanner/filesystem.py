import os
from dataclasses import dataclass
from pathlib import Path

from backend.app.services.repo_scanner.file_info import is_probably_binary
from backend.app.services.repo_scanner.ignore import IgnoreMatcher


@dataclass(frozen=True)
class FileSystemWalkResult:
    file_paths: list[Path]
    ignored_count: int
    skipped_count: int


class FileSystemWalker:
    def __init__(self, *, max_file_size_bytes: int = 2_000_000) -> None:
        self.max_file_size_bytes = max_file_size_bytes

    def walk(self, root: Path) -> FileSystemWalkResult:
        matcher = IgnoreMatcher(root)
        file_paths: list[Path] = []
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
                file_paths.append(file_path)

        return FileSystemWalkResult(
            file_paths=file_paths,
            ignored_count=ignored_count,
            skipped_count=skipped_count,
        )
