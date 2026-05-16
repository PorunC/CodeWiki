import tree_sitter_java

from backend.app.services.ast_parsers.augmenters.java import augment_java_symbols
from backend.app.services.ast_parsers.base import AstSymbol
from backend.app.services.ast_parsers.capture_specs.java import JAVA_CAPTURE_QUERY
from backend.app.services.ast_parsers.capture_engine import (
    CaptureLanguageSpec,
    CaptureParseContext,
    TreeSitterCaptureParser,
)


class TreeSitterJavaParser(TreeSitterCaptureParser):
    def __init__(self) -> None:
        super().__init__(
            CaptureLanguageSpec(
                language="java",
                grammar=tree_sitter_java.language,
                capture_query=JAVA_CAPTURE_QUERY,
            )
        )

    def augment_symbols(
        self,
        symbols: list[AstSymbol],
        context: CaptureParseContext,
    ) -> list[AstSymbol]:
        return augment_java_symbols(symbols, context)
