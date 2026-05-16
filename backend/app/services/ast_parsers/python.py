import tree_sitter_python

from backend.app.services.ast_parsers.augmenters.python import augment_python_symbols
from backend.app.services.ast_parsers.base import AstSymbol
from backend.app.services.ast_parsers.capture_specs.python import PYTHON_CAPTURE_QUERY
from backend.app.services.ast_parsers.capture_engine import (
    CaptureLanguageSpec,
    CaptureParseContext,
    TreeSitterCaptureParser,
)


class PythonAstParser(TreeSitterCaptureParser):
    def __init__(self) -> None:
        super().__init__(
            CaptureLanguageSpec(
                language="python",
                grammar=tree_sitter_python.language,
                capture_query=PYTHON_CAPTURE_QUERY,
            )
        )

    def augment_symbols(
        self,
        symbols: list[AstSymbol],
        context: CaptureParseContext,
    ) -> list[AstSymbol]:
        return augment_python_symbols(symbols, context)
