import tree_sitter_cpp

from backend.app.services.ast_parsers.augmenters.cpp import augment_cpp_symbols
from backend.app.services.ast_parsers.base import AstSymbol
from backend.app.services.ast_parsers.capture_engine import (
    CaptureLanguageSpec,
    CaptureParseContext,
    TreeSitterCaptureParser,
)
from backend.app.services.ast_parsers.capture_specs.cpp import CPP_CAPTURE_QUERY


class TreeSitterCppParser(TreeSitterCaptureParser):
    def __init__(self) -> None:
        super().__init__(
            CaptureLanguageSpec(
                language="cpp",
                grammar=tree_sitter_cpp.language,
                capture_query=CPP_CAPTURE_QUERY,
            )
        )

    def augment_symbols(
        self,
        symbols: list[AstSymbol],
        context: CaptureParseContext,
    ) -> list[AstSymbol]:
        return augment_cpp_symbols(symbols, context)
