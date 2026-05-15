from backend.app.services.ast_parsers.queries.native import (
    CPP_QUERY,
    CSHARP_QUERY,
    C_QUERY,
    RUST_QUERY,
)
from backend.app.services.ast_parsers.query import QueryLanguageSpec, TreeSitterQueryParser


class TreeSitterRustParser(TreeSitterQueryParser):
    def __init__(self) -> None:
        import tree_sitter_rust

        super().__init__(
            QueryLanguageSpec(
                language="rust",
                grammar=tree_sitter_rust.language,
                query=RUST_QUERY,
            )
        )


class TreeSitterCParser(TreeSitterQueryParser):
    def __init__(self) -> None:
        import tree_sitter_c

        super().__init__(
            QueryLanguageSpec(
                language="c",
                grammar=tree_sitter_c.language,
                query=C_QUERY,
            )
        )


class TreeSitterCppParser(TreeSitterQueryParser):
    def __init__(self) -> None:
        import tree_sitter_cpp

        super().__init__(
            QueryLanguageSpec(
                language="cpp",
                grammar=tree_sitter_cpp.language,
                query=CPP_QUERY,
            )
        )


class TreeSitterCSharpParser(TreeSitterQueryParser):
    def __init__(self) -> None:
        import tree_sitter_c_sharp

        super().__init__(
            QueryLanguageSpec(
                language="csharp",
                grammar=tree_sitter_c_sharp.language,
                query=CSHARP_QUERY,
            )
        )
