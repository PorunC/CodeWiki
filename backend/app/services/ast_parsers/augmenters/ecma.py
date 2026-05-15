from dataclasses import replace

from backend.app.services.ast_parsers.base import AstSymbol
from backend.app.services.ast_parsers.ecma.declarations import declaration_symbols
from backend.app.services.ast_parsers.ecma.endpoints import endpoint_symbols
from backend.app.services.ast_parsers.ecma.imports import import_names
from backend.app.services.ast_parsers.query import QueryParseContext, merge_enhanced_symbols


def augment_ecma_symbols(
    symbols: list[AstSymbol],
    context: QueryParseContext,
) -> list[AstSymbol]:
    exported_names: set[str] = set()
    declarations = declaration_symbols(
        root=context.root,
        source=context.source,
        file_path=context.file_path,
        file_hash=context.file_hash,
        language=context.language,
        exported_names=exported_names,
    )
    file_symbol = replace(
        symbols[0],
        imports=import_names(context.root, context.source),
        exports=sorted(exported_names),
        metadata={
            **symbols[0].metadata,
            "language_enhancer": "ecma",
        },
    )
    endpoints = endpoint_symbols(
        context.root,
        context.source,
        file_path=context.file_path,
        file_hash=context.file_hash,
        language=context.language,
    )
    return merge_enhanced_symbols(
        symbols,
        [file_symbol, *declarations, *endpoints],
        enhancer="ecma",
    )
