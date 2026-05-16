import tree_sitter_cpp

from backend.app.services.ast_parsers.capture_engine import (
    CaptureLanguageSpec,
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
