import tree_sitter_javascript
import tree_sitter_typescript

from backend.app.services.ast_parsers.augmenters.ecma import augment_ecma_symbols
from backend.app.services.ast_parsers.base import AstSymbol
from backend.app.services.ast_parsers.queries.ecma import JAVASCRIPT_QUERY, TYPESCRIPT_QUERY
from backend.app.services.ast_parsers.query import (
    QueryLanguageSpec,
    QueryParseContext,
    TreeSitterQueryParser,
)


class TreeSitterTypeScriptParser(TreeSitterQueryParser):
    def __init__(self, language: str) -> None:
        grammar = (
            tree_sitter_typescript.language_tsx
            if language == "tsx"
            else tree_sitter_typescript.language_typescript
        )
        super().__init__(
            QueryLanguageSpec(
                language=language,
                grammar=grammar,
                query=TYPESCRIPT_QUERY,
            )
        )

    def augment_symbols(
        self,
        symbols: list[AstSymbol],
        context: QueryParseContext,
    ) -> list[AstSymbol]:
        return augment_ecma_symbols(symbols, context)


class TreeSitterJavaScriptParser(TreeSitterQueryParser):
    def __init__(self, language: str) -> None:
        super().__init__(
            QueryLanguageSpec(
                language=language,
                grammar=tree_sitter_javascript.language,
                query=JAVASCRIPT_QUERY,
            )
        )

    def augment_symbols(
        self,
        symbols: list[AstSymbol],
        context: QueryParseContext,
    ) -> list[AstSymbol]:
        return augment_ecma_symbols(symbols, context)
