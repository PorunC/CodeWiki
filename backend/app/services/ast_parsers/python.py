import tree_sitter_python

from backend.app.services.ast_parsers.augmenters.python import augment_python_symbols
from backend.app.services.ast_parsers.base import AstSymbol
from backend.app.services.ast_parsers.queries.python import PYTHON_QUERY
from backend.app.services.ast_parsers.query import (
    QueryLanguageSpec,
    QueryParseContext,
    TreeSitterQueryParser,
)


class PythonAstParser(TreeSitterQueryParser):
    def __init__(self) -> None:
        super().__init__(
            QueryLanguageSpec(
                language="python",
                grammar=tree_sitter_python.language,
                query=PYTHON_QUERY,
            )
        )

    def augment_symbols(
        self,
        symbols: list[AstSymbol],
        context: QueryParseContext,
    ) -> list[AstSymbol]:
        return augment_python_symbols(symbols, context)
