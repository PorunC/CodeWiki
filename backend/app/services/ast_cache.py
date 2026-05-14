import json
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any

from backend.app.services.ast_parsers.base import AstSymbol

AST_CACHE_SCHEMA_VERSION = 1
_AST_SYMBOL_FIELDS = {field.name for field in fields(AstSymbol)}


class AstParseCache:
    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = cache_dir

    def read(self, file_hash: str, *, file_path: str, language: str) -> list[AstSymbol] | None:
        payload = self._read_payload(file_hash)
        if payload is None:
            return None
        entries = payload.get("entries")
        if not isinstance(entries, dict):
            return None
        entry = entries.get(file_path)
        if not isinstance(entry, dict) or entry.get("language") != language:
            return None
        raw_symbols = entry.get("symbols")
        if not isinstance(raw_symbols, list):
            return None
        try:
            return [_symbol_from_json(item) for item in raw_symbols if isinstance(item, dict)]
        except TypeError:
            return None

    def write(
        self,
        file_hash: str,
        *,
        file_path: str,
        language: str,
        symbols: list[AstSymbol],
    ) -> None:
        payload = self._read_payload(file_hash) or {
            "schema_version": AST_CACHE_SCHEMA_VERSION,
            "entries": {},
        }
        entries = payload.setdefault("entries", {})
        if not isinstance(entries, dict):
            entries = {}
            payload["entries"] = entries
        entries[file_path] = {
            "language": language,
            "symbols": [asdict(symbol) for symbol in symbols],
        }
        path = self.path_for(file_hash)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = path.with_suffix(f"{path.suffix}.tmp")
            temp_path.write_text(
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )
            temp_path.replace(path)
        except OSError:
            return

    def path_for(self, file_hash: str) -> Path:
        return self.cache_dir / f"{file_hash}.json"

    def _read_payload(self, file_hash: str) -> dict[str, Any] | None:
        path = self.path_for(file_hash)
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        if payload.get("schema_version") != AST_CACHE_SCHEMA_VERSION:
            return None
        return payload


def _symbol_from_json(payload: dict[str, Any]) -> AstSymbol:
    values = {key: value for key, value in payload.items() if key in _AST_SYMBOL_FIELDS}
    return AstSymbol(**values)
