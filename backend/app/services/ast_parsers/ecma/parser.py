from pathlib import Path

from tree_sitter import Language, Parser
import tree_sitter_javascript
import tree_sitter_typescript

from backend.app.services.ast_parsers.base import AstSymbol
from backend.app.services.ast_parsers.common import content_hash, relative_path
from backend.app.services.ast_parsers.ecma.declarations import declaration_symbols
from backend.app.services.ast_parsers.ecma.endpoints import endpoint_symbols
from backend.app.services.ast_parsers.ecma.imports import import_names


class TreeSitterTypeScriptParser:
    def __init__(self, language: str) -> None:
        self.language = language
        grammar = (
            tree_sitter_typescript.language_tsx()
            if language == "tsx"
            else tree_sitter_typescript.language_typescript()
        )
        self.parser = Parser(Language(grammar))

    def parse(self, path: Path, *, repo_root: Path | None = None) -> list[AstSymbol]:
        return TreeSitterEcmaParser(self.language, self.parser).parse(path, repo_root=repo_root)


class TreeSitterJavaScriptParser:
    def __init__(self, language: str) -> None:
        self.language = language
        self.parser = Parser(Language(tree_sitter_javascript.language()))

    def parse(self, path: Path, *, repo_root: Path | None = None) -> list[AstSymbol]:
        return TreeSitterEcmaParser(self.language, self.parser).parse(path, repo_root=repo_root)


class TreeSitterEcmaParser:
    def __init__(self, language: str, parser: Parser) -> None:
        self.language = language
        self.parser = parser

    def parse(self, path: Path, *, repo_root: Path | None = None) -> list[AstSymbol]:
        content = path.read_text(encoding="utf-8", errors="replace")
        source = content.encode("utf-8")
        tree = self.parser.parse(source)
        root = tree.root_node
        file_path = relative_path(path, repo_root)
        file_hash = content_hash(content)
        lines = content.splitlines()
        imports = import_names(root, source)
        exported_names: set[str] = set()

        symbols = [
            AstSymbol(
                id=f"file:{file_path}",
                type="file",
                name=path.name,
                file_path=file_path,
                language=self.language,
                start_line=1,
                end_line=max(len(lines), 1),
                imports=imports,
                hash=file_hash,
                metadata={"tree_sitter": True, "root_type": root.type},
            )
        ]
        symbols.extend(
            declaration_symbols(
                root=root,
                source=source,
                file_path=file_path,
                file_hash=file_hash,
                language=self.language,
                exported_names=exported_names,
            )
        )
        symbols[0] = AstSymbol(
            **{
                **symbols[0].__dict__,
                "exports": sorted(exported_names),
            }
        )
        symbols.extend(
            endpoint_symbols(
                root,
                source,
                file_path=file_path,
                file_hash=file_hash,
                language=self.language,
            )
        )
        return symbols
