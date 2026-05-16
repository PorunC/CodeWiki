import tree_sitter_c

from backend.app.services.ast_parsers.augmenters.c import augment_c_symbols
from backend.app.services.ast_parsers.base import AstSymbol
from backend.app.services.ast_parsers.capture_engine import (
    CaptureLanguageSpec,
    CaptureParseContext,
    TreeSitterCaptureParser,
)
from backend.app.services.ast_parsers.capture_specs.c import C_CAPTURE_QUERY


class TreeSitterCParser(TreeSitterCaptureParser):
    def __init__(self) -> None:
        super().__init__(
            CaptureLanguageSpec(
                language="c",
                grammar=tree_sitter_c.language,
                capture_query=C_CAPTURE_QUERY,
            )
        )

    def augment_symbols(
        self,
        symbols: list[AstSymbol],
        context: CaptureParseContext,
    ) -> list[AstSymbol]:
        return augment_c_symbols(symbols, context)
