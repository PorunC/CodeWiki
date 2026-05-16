import tree_sitter_rust

from backend.app.services.ast_parsers.capture_engine import (
    CaptureLanguageSpec,
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
