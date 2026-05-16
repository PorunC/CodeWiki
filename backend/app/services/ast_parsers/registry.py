from pathlib import Path

from backend.app.config import get_settings
from backend.app.services.ast_cache import AstParseCache
from backend.app.services.ast_parsers.base import AstSymbol, LanguageParser
from backend.app.services.ast_parsers.common import relative_path
from backend.app.services.language_detector import LanguageDetector
from backend.app.services.repo_scanner.file_info import sha256_file


class AstParserRegistry:
    def __init__(self) -> None:
        self._parsers: dict[str, LanguageParser] = {}

    @classmethod
    def default(cls) -> "AstParserRegistry":
        from backend.app.services.ast_parsers.ecma import (
            TreeSitterJavaScriptParser,
            TreeSitterTypeScriptParser,
        )
        from backend.app.services.ast_parsers.c import TreeSitterCParser
        from backend.app.services.ast_parsers.cpp import TreeSitterCppParser
        from backend.app.services.ast_parsers.csharp import TreeSitterCSharpParser
        from backend.app.services.ast_parsers.go import TreeSitterGoParser
        from backend.app.services.ast_parsers.java import TreeSitterJavaParser
        from backend.app.services.ast_parsers.python import PythonAstParser
        from backend.app.services.ast_parsers.rust import TreeSitterRustParser

        registry = cls()
        registry.register(PythonAstParser())
        registry.register(TreeSitterJavaParser())
        registry.register(TreeSitterGoParser())
        registry.register(TreeSitterRustParser())
        registry.register(TreeSitterCParser())
        registry.register(TreeSitterCppParser())
        registry.register(TreeSitterCSharpParser())
        registry.register(TreeSitterTypeScriptParser("typescript"))
        registry.register(TreeSitterTypeScriptParser("tsx"))
        registry.register(TreeSitterJavaScriptParser("javascript"))
        registry.register(TreeSitterJavaScriptParser("jsx"))
        return registry

    def register(self, parser: LanguageParser) -> None:
        self._parsers[parser.language] = parser

    def get(self, language: str) -> LanguageParser | None:
        return self._parsers.get(language)

    def supported_languages(self) -> list[str]:
        return sorted(self._parsers)


class AstParser:
    def __init__(
        self,
        *,
        registry: AstParserRegistry | None = None,
        language_detector: LanguageDetector | None = None,
        cache_dir: Path | None = None,
        cache_enabled: bool = True,
    ) -> None:
        self.registry = registry or AstParserRegistry.default()
        self.language_detector = language_detector or LanguageDetector()
        self.cache = (
            AstParseCache(cache_dir or get_settings().storage_dir / "cache" / "ast")
            if cache_enabled
            else None
        )

    def parse_file(
        self,
        path: Path,
        *,
        repo_root: Path | None = None,
        language: str | None = None,
        file_hash: str | None = None,
    ) -> list[AstSymbol]:
        detected_language = language or self.language_detector.detect(path)
        parser = self.registry.get(detected_language)
        if parser is None:
            return []
        relative_file_path = relative_path(path, repo_root)
        cache_hash = file_hash or sha256_file(path)
        if self.cache is not None:
            cached_symbols = self.cache.read(
                cache_hash,
                file_path=relative_file_path,
                language=detected_language,
            )
            if cached_symbols is not None:
                return cached_symbols
        symbols = parser.parse(path, repo_root=repo_root)
        if self.cache is not None:
            self.cache.write(
                cache_hash,
                file_path=relative_file_path,
                language=detected_language,
                symbols=symbols,
            )
        return symbols
