import tree_sitter_go

from backend.app.services.ast_parsers.augmenters.go import augment_go_symbols
from backend.app.services.ast_parsers.base import AstSymbol
from backend.app.services.ast_parsers.capture_specs.go import GO_CAPTURE_QUERY
from backend.app.services.ast_parsers.capture_engine import (
    CaptureLanguageSpec,
    CaptureParseContext,
    TreeSitterCaptureParser,
)


class TreeSitterGoParser(TreeSitterCaptureParser):
    def __init__(self) -> None:
        super().__init__(
            CaptureLanguageSpec(
                language="go",
                grammar=tree_sitter_go.language,
                capture_query=GO_CAPTURE_QUERY,
            )
        )

    def augment_symbols(
        self,
        symbols: list[AstSymbol],
        context: CaptureParseContext,
    ) -> list[AstSymbol]:
        return augment_go_symbols(symbols, context)
