from backend.app.services.ast_parsers.base import AstSymbol
from backend.app.services.ast_parsers.capture_engine import (
    CaptureParseContext,
    merge_enhanced_symbols,
)


def augment_capture_only_symbols(
    symbols: list[AstSymbol],
    context: CaptureParseContext,
    *,
    enhancer: str,
) -> list[AstSymbol]:
    return merge_enhanced_symbols(symbols, [], enhancer=enhancer)
