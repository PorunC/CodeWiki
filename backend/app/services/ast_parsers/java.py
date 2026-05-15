import tree_sitter_java

from backend.app.services.ast_parsers.augmenters.java import augment_java_symbols
from backend.app.services.ast_parsers.base import AstSymbol
from backend.app.services.ast_parsers.queries.java import JAVA_QUERY
from backend.app.services.ast_parsers.query import (
    QueryLanguageSpec,
    QueryParseContext,
    TreeSitterQueryParser,
)


class TreeSitterJavaParser(TreeSitterQueryParser):
    def __init__(self) -> None:
        super().__init__(
            QueryLanguageSpec(
                language="java",
                grammar=tree_sitter_java.language,
                query=JAVA_QUERY,
            )
        )

    def augment_symbols(
        self,
        symbols: list[AstSymbol],
        context: QueryParseContext,
    ) -> list[AstSymbol]:
        return augment_java_symbols(symbols, context)
