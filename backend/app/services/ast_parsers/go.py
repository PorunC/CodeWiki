import tree_sitter_go

from backend.app.services.ast_parsers.augmenters.go import augment_go_symbols
from backend.app.services.ast_parsers.base import AstSymbol
from backend.app.services.ast_parsers.queries.go import GO_QUERY
from backend.app.services.ast_parsers.query import (
    QueryLanguageSpec,
    QueryParseContext,
    TreeSitterQueryParser,
)


class TreeSitterGoParser(TreeSitterQueryParser):
    def __init__(self) -> None:
        super().__init__(
            QueryLanguageSpec(
                language="go",
                grammar=tree_sitter_go.language,
                query=GO_QUERY,
            )
        )

    def augment_symbols(
        self,
        symbols: list[AstSymbol],
        context: QueryParseContext,
    ) -> list[AstSymbol]:
        return augment_go_symbols(symbols, context)
