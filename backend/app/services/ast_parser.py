from collections.abc import Iterable
from pathlib import Path

from backend.app.services.ast_parsers import (
    AstParser,
    AstParserRegistry,
    AstSymbol,
    LanguageParser,
    PythonAstParser,
    TreeSitterGoParser,
    TreeSitterJavaParser,
    TreeSitterJavaScriptParser,
    TreeSitterTypeScriptParser,
)
from backend.app.services.repo_scanner import ScannedFile


def parse_scanned_files(
    parser: AstParser,
    files: Iterable[ScannedFile],
    *,
    repo_root: Path,
    only_paths: set[str] | None = None,
) -> tuple[list[AstSymbol], list[dict[str, str]]]:
    symbols: list[AstSymbol] = []
    errors: list[dict[str, str]] = []

    for scanned_file in files:
        if only_paths is not None and scanned_file.path not in only_paths:
            continue
        if not scanned_file.is_source:
            continue
        try:
            parsed_symbols = parser.parse_file(
                Path(scanned_file.absolute_path),
                repo_root=repo_root,
                language=scanned_file.language,
                file_hash=scanned_file.sha256,
            )
        except SyntaxError as exc:
            errors.append({"file_path": scanned_file.path, "error": str(exc)})
            continue
        symbols.extend(parsed_symbols)
    return symbols, errors

__all__ = [
    "AstParser",
    "AstParserRegistry",
    "AstSymbol",
    "LanguageParser",
    "PythonAstParser",
    "TreeSitterGoParser",
    "TreeSitterJavaParser",
    "TreeSitterJavaScriptParser",
    "TreeSitterTypeScriptParser",
    "parse_scanned_files",
]
