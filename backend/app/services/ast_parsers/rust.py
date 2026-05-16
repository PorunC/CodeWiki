import tree_sitter_rust

from backend.app.services.ast_parsers.augmenters.rust import augment_rust_symbols
from backend.app.services.ast_parsers.base import AstSymbol
from backend.app.services.ast_parsers.capture_engine import (
    CaptureLanguageSpec,
    CaptureParseContext,
    TreeSitterCaptureParser,
)
from backend.app.services.ast_parsers.capture_specs.rust import RUST_CAPTURE_QUERY


class TreeSitterRustParser(TreeSitterCaptureParser):
    def __init__(self) -> None:
        super().__init__(
            CaptureLanguageSpec(
                language="rust",
                grammar=tree_sitter_rust.language,
                capture_query=RUST_CAPTURE_QUERY,
            )
        )

    def augment_symbols(
        self,
        symbols: list[AstSymbol],
        context: CaptureParseContext,
    ) -> list[AstSymbol]:
        return augment_rust_symbols(symbols, context)
