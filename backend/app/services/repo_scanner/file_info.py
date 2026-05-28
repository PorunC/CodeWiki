import hashlib
from datetime import UTC, datetime
from os import stat_result
from pathlib import Path

from backend.app.services.language_detector import LanguageDetector
from backend.app.services.repo_scanner.models import RepoFile, ScannedFile


def scan_file_metadata(
    root: Path,
    file_path: Path,
    language_detector: LanguageDetector,
    *,
    stat: stat_result | None = None,
) -> RepoFile:
    stat = stat or file_path.stat()
    language = language_detector.detect(file_path)
    return RepoFile(
        path=file_path.relative_to(root).as_posix(),
        absolute_path=str(file_path),
        language=language,
        is_source=language_detector.is_source_language(language),
        size_bytes=stat.st_size,
        modified_at=modified_at_iso(stat),
    )


def scan_file(
    root: Path,
    file_path: Path,
    language_detector: LanguageDetector,
    *,
    known_sha256: str | None = None,
    stat: stat_result | None = None,
) -> ScannedFile:
    stat = stat or file_path.stat()
    metadata = scan_file_metadata(root, file_path, language_detector, stat=stat)
    return ScannedFile(
        path=metadata.path,
        absolute_path=metadata.absolute_path,
        language=metadata.language,
        is_source=metadata.is_source,
        size_bytes=metadata.size_bytes,
        modified_at=metadata.modified_at,
        sha256=known_sha256 or sha256_file(file_path),
    )


def sha256_file(file_path: Path) -> str:
    digest = hashlib.sha256()
    with file_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_probably_binary(file_path: Path) -> bool:
    with file_path.open("rb") as handle:
        sample = handle.read(4096)
    return b"\0" in sample


def modified_at_iso(stat: stat_result) -> str:
    return datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat()
