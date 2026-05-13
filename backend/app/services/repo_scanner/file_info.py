import hashlib
from datetime import UTC, datetime
from pathlib import Path

from backend.app.services.language_detector import LanguageDetector
from backend.app.services.repo_scanner.models import ScannedFile


def scan_file(root: Path, file_path: Path, language_detector: LanguageDetector) -> ScannedFile:
    stat = file_path.stat()
    language = language_detector.detect(file_path)
    return ScannedFile(
        path=file_path.relative_to(root).as_posix(),
        absolute_path=str(file_path),
        language=language,
        is_source=language_detector.is_source_language(language),
        size_bytes=stat.st_size,
        sha256=sha256_file(file_path),
        modified_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
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
