import tree_sitter_c_sharp

from backend.app.services.ast_parsers.augmenters.csharp import augment_csharp_symbols
from backend.app.services.ast_parsers.base import AstSymbol
from backend.app.services.ast_parsers.capture_engine import (
    CaptureLanguageSpec,
    CaptureParseContext,
    TreeSitterCaptureParser,
)
from backend.app.services.ast_parsers.capture_specs.csharp import CSHARP_CAPTURE_QUERY


class TreeSitterCSharpParser(TreeSitterCaptureParser):
    def __init__(self) -> None:
        super().__init__(
            CaptureLanguageSpec(
                language="csharp",
                grammar=tree_sitter_c_sharp.language,
                capture_query=CSHARP_CAPTURE_QUERY,
            )
        )

    def augment_symbols(
        self,
        symbols: list[AstSymbol],
        context: CaptureParseContext,
    ) -> list[AstSymbol]:
        return augment_csharp_symbols(symbols, context)
