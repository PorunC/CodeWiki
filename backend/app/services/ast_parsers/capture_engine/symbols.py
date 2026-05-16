from dataclasses import replace
from typing import Any

from backend.app.services.ast_parsers.base import AstSymbol


def merge_enhanced_symbols(
    query_symbols: list[AstSymbol],
    enhanced_symbols: list[AstSymbol],
    *,
    enhancer: str,
) -> list[AstSymbol]:
    """Merge language-enhancer output into query-captured symbols by stable id."""
    enhanced_by_id = {symbol.id: symbol for symbol in enhanced_symbols}
    seen: set[str] = set()
    merged: list[AstSymbol] = []
    for query_symbol in query_symbols:
        enhanced_symbol = enhanced_by_id.get(query_symbol.id)
        if enhanced_symbol is None:
            merged.append(_mark_enhanced(query_symbol, enhancer=enhancer))
        else:
            merged.append(
                _mark_enhanced(
                    enhanced_symbol,
                    enhancer=enhancer,
                    query_symbol=query_symbol,
                )
            )
        seen.add(query_symbol.id)

    for enhanced_symbol in enhanced_symbols:
        if enhanced_symbol.id not in seen:
            merged.append(_mark_enhanced(enhanced_symbol, enhancer=enhancer))
    return merged


def _mark_enhanced(
    symbol: AstSymbol,
    *,
    enhancer: str,
    query_symbol: AstSymbol | None = None,
) -> AstSymbol:
    metadata: dict[str, Any] = {}
    if query_symbol is not None:
        metadata.update(query_symbol.metadata)
    metadata.update(symbol.metadata)
    metadata["language_enhancer"] = enhancer
    if query_symbol is not None or symbol.metadata.get("tree_sitter_capture"):
        metadata["tree_sitter_capture"] = True
    return replace(symbol, metadata=metadata)
