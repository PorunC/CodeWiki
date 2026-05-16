import tree_sitter_javascript
import tree_sitter_typescript

from backend.app.services.ast_parsers.augmenters.ecma import augment_ecma_symbols
from backend.app.services.ast_parsers.base import AstSymbol
from backend.app.services.ast_parsers.capture_specs.ecma import JAVASCRIPT_CAPTURE_QUERY, TYPESCRIPT_CAPTURE_QUERY
from backend.app.services.ast_parsers.capture_engine import (
    CaptureLanguageSpec,
    CaptureParseContext,
    TreeSitterCaptureParser,
)


class TreeSitterTypeScriptParser(TreeSitterCaptureParser):
    def __init__(self, language: str) -> None:
        grammar = (
            tree_sitter_typescript.language_tsx
            if language == "tsx"
            else tree_sitter_typescript.language_typescript
        )
        super().__init__(
            CaptureLanguageSpec(
                language=language,
                grammar=grammar,
                capture_query=TYPESCRIPT_CAPTURE_QUERY,
            )
        )

    def augment_symbols(
        self,
        symbols: list[AstSymbol],
        context: CaptureParseContext,
    ) -> list[AstSymbol]:
        return augment_ecma_symbols(symbols, context)


class TreeSitterJavaScriptParser(TreeSitterCaptureParser):
    def __init__(self, language: str) -> None:
        super().__init__(
            CaptureLanguageSpec(
                language=language,
                grammar=tree_sitter_javascript.language,
                capture_query=JAVASCRIPT_CAPTURE_QUERY,
            )
        )

    def augment_symbols(
        self,
        symbols: list[AstSymbol],
        context: CaptureParseContext,
    ) -> list[AstSymbol]:
        return augment_ecma_symbols(symbols, context)
