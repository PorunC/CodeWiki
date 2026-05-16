from backend.app.services.ast_parsers.augmenters.capture_only import (
    augment_capture_only_symbols,
)
from backend.app.services.ast_parsers.base import AstSymbol
from backend.app.services.ast_parsers.capture_engine import CaptureParseContext


def augment_rust_symbols(
    symbols: list[AstSymbol],
    context: CaptureParseContext,
) -> list[AstSymbol]:
    return augment_capture_only_symbols(symbols, context, enhancer="rust")
