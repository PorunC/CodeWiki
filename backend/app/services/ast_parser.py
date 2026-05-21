from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path

from backend.app.services.ast_parsers import (
    AstParser,
    AstParserRegistry,
    AstSymbol,
    LanguageParser,
    PythonAstParser,
    TreeSitterCParser,
    TreeSitterCppParser,
    TreeSitterCSharpParser,
    TreeSitterGoParser,
    TreeSitterJavaParser,
    TreeSitterJavaScriptParser,
    TreeSitterRustParser,
    TreeSitterTypeScriptParser,
)
from backend.app.services.repo_scanner import ScannedFile
from backend.app.services.source_file_cache import SourceFileContentProvider


def parse_scanned_files(
    parser: AstParser,
    files: Iterable[ScannedFile],
    *,
    repo_root: Path,
    only_paths: set[str] | None = None,
    max_workers: int | None = None,
    content_provider: SourceFileContentProvider | None = None,
) -> tuple[list[AstSymbol], list[dict[str, str]]]:
    candidates = [
        scanned_file
        for scanned_file in files
        if scanned_file.is_source and (only_paths is None or scanned_file.path in only_paths)
    ]
    worker_count = _parse_worker_count(len(candidates), max_workers)
    if content_provider is not None:
        parser.content_provider = content_provider
    if worker_count <= 1:
        return _parse_scanned_files_sequential(parser, candidates, repo_root=repo_root)

    results: list[tuple[int, list[AstSymbol], dict[str, str] | None]] = []
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = [
            executor.submit(_parse_scanned_file_worker, parser, index, scanned_file, repo_root)
            for index, scanned_file in enumerate(candidates)
        ]
        for future in futures:
            results.append(future.result())

    symbols: list[AstSymbol] = []
    errors: list[dict[str, str]] = []
    for _index, parsed_symbols, error in sorted(results, key=lambda item: item[0]):
        if error is not None:
            errors.append(error)
        else:
            symbols.extend(parsed_symbols)
    return symbols, errors


def _parse_scanned_files_sequential(
    parser: AstParser,
    files: list[ScannedFile],
    *,
    repo_root: Path,
) -> tuple[list[AstSymbol], list[dict[str, str]]]:
    symbols: list[AstSymbol] = []
    errors: list[dict[str, str]] = []
    for scanned_file in files:
        try:
            parsed_symbols = _parse_one_file(parser, scanned_file, repo_root=repo_root)
        except SyntaxError as exc:
            errors.append({"file_path": scanned_file.path, "error": str(exc)})
            continue
        symbols.extend(parsed_symbols)
    return symbols, errors


def _parse_scanned_file_worker(
    parser: AstParser,
    index: int,
    scanned_file: ScannedFile,
    repo_root: Path,
) -> tuple[int, list[AstSymbol], dict[str, str] | None]:
    worker_parser = parser.fork()
    try:
        return index, _parse_one_file(worker_parser, scanned_file, repo_root=repo_root), None
    except SyntaxError as exc:
        return index, [], {"file_path": scanned_file.path, "error": str(exc)}


def _parse_one_file(parser: AstParser, scanned_file: ScannedFile, *, repo_root: Path) -> list[AstSymbol]:
    return parser.parse_file(
        Path(scanned_file.absolute_path),
        repo_root=repo_root,
        language=scanned_file.language,
        file_hash=scanned_file.sha256,
    )


def _parse_worker_count(file_count: int, requested_workers: int | None) -> int:
    if file_count < 2:
        return 1
    if requested_workers is not None:
        return max(1, min(requested_workers, file_count))
    env_value = os.getenv("CODEWIKI_AST_PARSE_WORKERS")
    if env_value:
        try:
            return max(1, min(int(env_value), file_count))
        except ValueError:
            return 1
    return max(1, min(file_count, (os.cpu_count() or 2), 4))

__all__ = [
    "AstParser",
    "AstParserRegistry",
    "AstSymbol",
    "LanguageParser",
    "PythonAstParser",
    "TreeSitterCParser",
    "TreeSitterCppParser",
    "TreeSitterCSharpParser",
    "TreeSitterGoParser",
    "TreeSitterJavaParser",
    "TreeSitterJavaScriptParser",
    "TreeSitterRustParser",
    "TreeSitterTypeScriptParser",
    "parse_scanned_files",
]
