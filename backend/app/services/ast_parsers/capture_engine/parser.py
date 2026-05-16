from pathlib import Path

from tree_sitter import Language, Parser, Query

from backend.app.services.ast_parsers.base import AstSymbol
from backend.app.services.ast_parsers.common import content_hash, relative_path
from backend.app.services.ast_parsers.capture_engine.captures import (
    assign_calls,
    assign_containment_parents,
    merge_records,
    records_from_capture_query,
)
from backend.app.services.ast_parsers.capture_engine.models import DefinitionRecord, CaptureLanguageSpec
from backend.app.services.ast_parsers.capture_engine.models import CaptureParseContext
from backend.app.services.ast_parsers.capture_engine.normalization import signature_text
from backend.app.services.ast_parsers.tree import end_line, start_line


class TreeSitterCaptureParser:
    """Tree-sitter parser driven by unified semantic capture names."""

    def __init__(self, spec: CaptureLanguageSpec) -> None:
        self.language = spec.language
        self._language = Language(spec.grammar())
        self._parser = Parser(self._language)
        self._capture_query = Query(self._language, spec.capture_query)

    def parse(self, path: Path, *, repo_root: Path | None = None) -> list[AstSymbol]:
        content = path.read_text(encoding="utf-8", errors="replace")
        source = content.encode("utf-8")
        tree = self._parser.parse(source)
        root = tree.root_node
        file_path = relative_path(path, repo_root)
        file_hash = content_hash(content)
        lines = content.splitlines()
        context = CaptureParseContext(
            path=path,
            repo_root=repo_root,
            file_path=file_path,
            file_hash=file_hash,
            content=content,
            source=source,
            root=root,
            lines=lines,
            language=self.language,
        )

        records, imports = records_from_capture_query(self._capture_query, root, source)
        assign_containment_parents(records)
        assign_calls(self._capture_query, root, source, records)
        merged = merge_records(records)
        exports = sorted(record.name for record in merged if record.parent_name == "" or record.exported)

        file_symbol = AstSymbol(
            id=f"file:{file_path}",
            type="file",
            name=path.name,
            file_path=file_path,
            language=self.language,
            start_line=1,
            end_line=max(len(lines), 1),
            imports=imports,
            exports=exports,
            hash=file_hash,
            metadata={
                "tree_sitter": True,
                "tree_sitter_capture": True,
                "root_type": root.type,
            },
        )
        symbols = [
            file_symbol,
            *[
                self._symbol(record, file_path=file_path, file_hash=file_hash)
                for record in sorted(
                    merged,
                    key=lambda item: (item.node.start_byte, item.node.end_byte, item.kind, item.name),
                )
            ],
        ]
        return self.augment_symbols(symbols, context)

    def augment_symbols(
        self,
        symbols: list[AstSymbol],
        context: CaptureParseContext,
    ) -> list[AstSymbol]:
        return symbols

    def _symbol(self, record: DefinitionRecord, *, file_path: str, file_hash: str) -> AstSymbol:
        parent_id = f"{file_path}::{record.parent_name}" if record.parent_name else None
        symbol_id = (
            f"{parent_id}.{record.name}"
            if parent_id is not None
            else f"{file_path}::{record.name}"
        )
        return AstSymbol(
            id=symbol_id,
            type=record.kind,
            name=record.name,
            file_path=file_path,
            language=self.language,
            start_line=start_line(record.node),
            end_line=end_line(record.node),
            parent_id=parent_id,
            signature=signature_text(record.node, self.language),
            bases=sorted(record.bases),
            implements=sorted(record.implements),
            calls=sorted(record.calls),
            references=sorted(record.references),
            hash=file_hash,
            metadata={
                "exported": record.exported or not record.parent_name,
                "tree_sitter_capture": True,
                "tree_sitter_type": record.node.type,
            },
        )
