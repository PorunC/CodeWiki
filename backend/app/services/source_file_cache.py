from pathlib import Path
from threading import Lock


class SourceFileContentProvider:
    """Thread-safe per-repository text cache for repeated source reads."""

    def __init__(self, repo_root: Path | str) -> None:
        self.repo_root = Path(repo_root).resolve()
        self._texts: dict[str, str] = {}
        self._lock = Lock()

    def read_text(self, path: Path | str) -> str:
        resolved = Path(path).resolve()
        key = self._cache_key(resolved)
        with self._lock:
            cached = self._texts.get(key)
        if cached is not None:
            return cached

        content = resolved.read_text(encoding="utf-8", errors="replace")
        with self._lock:
            return self._texts.setdefault(key, content)

    def read_lines(self, path: Path | str) -> list[str]:
        return self.read_text(path).splitlines()

    def _cache_key(self, path: Path) -> str:
        try:
            return path.relative_to(self.repo_root).as_posix()
        except ValueError:
            return path.as_posix()
