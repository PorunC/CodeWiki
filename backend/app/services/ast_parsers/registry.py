from pathlib import Path

from backend.app.services.ast_parsers.base import AstSymbol, LanguageParser
from backend.app.services.language_detector import LanguageDetector


class AstParserRegistry:
    def __init__(self) -> None:
        self._parsers: dict[str, LanguageParser] = {}

    @classmethod
    def default(cls) -> "AstParserRegistry":
        from backend.app.services.ast_parsers.ecma import (
            TreeSitterJavaScriptParser,
            TreeSitterTypeScriptParser,
        )
        from backend.app.services.ast_parsers.python import PythonAstParser

        registry = cls()
        registry.register(PythonAstParser())
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
    ) -> None:
        self.registry = registry or AstParserRegistry.default()
        self.language_detector = language_detector or LanguageDetector()

    def parse_file(
        self,
        path: Path,
        *,
        repo_root: Path | None = None,
        language: str | None = None,
    ) -> list[AstSymbol]:
        detected_language = language or self.language_detector.detect(path)
        parser = self.registry.get(detected_language)
        if parser is None:
            return []
        return parser.parse(path, repo_root=repo_root)
