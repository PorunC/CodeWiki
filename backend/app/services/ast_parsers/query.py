from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable

from tree_sitter import Language, Parser, Query, QueryCursor

from backend.app.services.ast_parsers.base import AstSymbol
from backend.app.services.ast_parsers.common import content_hash, relative_path
from backend.app.services.ast_parsers.ecma.tree import end_line, node_text, start_line

DEFINITION_PREFIX = "definition."
DEFINITION_META_CAPTURES = {"definition.name", "definition.parent", "definition.exported"}


@dataclass(frozen=True)
class QueryLanguageSpec:
    language: str
    grammar: Callable[[], Any]
    query: str


@dataclass(frozen=True)
class QueryParseContext:
    path: Path
    repo_root: Path | None
    file_path: str
    file_hash: str
    content: str
    source: bytes
    root: Any
    lines: list[str]
    language: str


@dataclass
class _DefinitionRecord:
    kind: str
    node: Any
    name: str
    parent_name: str = ""
    bases: set[str] = field(default_factory=set)
    implements: set[str] = field(default_factory=set)
    calls: set[str] = field(default_factory=set)
    references: set[str] = field(default_factory=set)
    exported: bool = False


class TreeSitterQueryParser:
    """Tree-sitter parser driven by unified semantic capture names.

    Language-specific S-expression queries should emit stable capture tags like
    @definition.class, @definition.name, @call.name, and @import.source. The
    adapter below converts those captures into CodeWiki's AstSymbol model.
    """

    def __init__(self, spec: QueryLanguageSpec) -> None:
        self.language = spec.language
        self._language = Language(spec.grammar())
        self._parser = Parser(self._language)
        self._query = Query(self._language, spec.query)

    def parse(self, path: Path, *, repo_root: Path | None = None) -> list[AstSymbol]:
        content = path.read_text(encoding="utf-8", errors="replace")
        source = content.encode("utf-8")
        tree = self._parser.parse(source)
        root = tree.root_node
        file_path = relative_path(path, repo_root)
        file_hash = content_hash(content)
        lines = content.splitlines()
        context = QueryParseContext(
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

        records, imports = self._records(root, source)
        self._assign_containment_parents(records)
        self._assign_calls(root, source, records)
        merged = self._merged_records(records)
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
                "tree_sitter_query": True,
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
        context: QueryParseContext,
    ) -> list[AstSymbol]:
        """Apply language-specific semantic enrichment after capture extraction."""
        return symbols

    def _records(self, root, source: bytes) -> tuple[list[_DefinitionRecord], list[str]]:
        records: list[_DefinitionRecord] = []
        imports: set[str] = set()
        cursor = QueryCursor(self._query)
        for _, captures in cursor.matches(root):
            for import_node in captures.get("import.source", []):
                value = normalize_import(node_text(import_node, source))
                if value:
                    imports.add(value)

            definition_capture = definition_capture_name(captures)
            if definition_capture is None:
                continue
            definition_node = captures[definition_capture][0]
            name_node = first_capture(captures, "definition.name")
            if name_node is None:
                continue
            name = normalize_identifier(node_text(name_node, source))
            if not name:
                continue
            parent_node = first_capture(captures, "definition.parent")
            parent_name = normalize_identifier(node_text(parent_node, source)) if parent_node else ""
            record = _DefinitionRecord(
                kind=definition_capture.removeprefix(DEFINITION_PREFIX),
                node=definition_node,
                name=name,
                parent_name=parent_name,
                exported=bool(captures.get("definition.exported")),
            )
            for base_node in captures.get("heritage.base", []):
                base = normalize_identifier(node_text(base_node, source))
                if base:
                    record.bases.add(base)
            for implemented_node in captures.get("heritage.implements", []):
                implemented = normalize_identifier(node_text(implemented_node, source))
                if implemented:
                    record.implements.add(implemented)
            records.append(record)
        return records, sorted(imports)

    def _assign_containment_parents(self, records: list[_DefinitionRecord]) -> None:
        containers = [
            record
            for record in records
            if record.kind in {"class", "interface", "schema"} and not record.parent_name
        ]
        for record in records:
            if record.parent_name or record.kind not in {"method", "function"}:
                continue
            parent = nearest_container(record.node, containers)
            if parent is not None:
                record.kind = "method"
                record.parent_name = parent.name

    def _assign_calls(self, root, source: bytes, records: list[_DefinitionRecord]) -> None:
        if not records:
            return
        cursor = QueryCursor(self._query)
        for _, captures in cursor.matches(root):
            for call_node in captures.get("call.name", []):
                call_name = normalize_identifier(node_text(call_node, source))
                if not call_name:
                    continue
                owner = innermost_owner(call_node, records)
                if owner is not None:
                    owner.calls.add(call_name)
            for reference_node in captures.get("reference.name", []):
                reference_name = normalize_identifier(node_text(reference_node, source))
                if not reference_name:
                    continue
                owner = innermost_owner(reference_node, records)
                if owner is not None:
                    owner.references.add(reference_name)

    def _merged_records(self, records: list[_DefinitionRecord]) -> list[_DefinitionRecord]:
        merged: dict[tuple[str, str, str], _DefinitionRecord] = {}
        parented_nodes = {
            (record.node.start_byte, record.node.end_byte, record.name)
            for record in records
            if record.parent_name
        }
        for record in records:
            if (
                not record.parent_name
                and record.kind == "function"
                and (record.node.start_byte, record.node.end_byte, record.name) in parented_nodes
            ):
                continue
            key = (record.kind, record.parent_name, record.name)
            previous = merged.get(key)
            if previous is None:
                merged[key] = record
                continue
            previous.bases.update(record.bases)
            previous.implements.update(record.implements)
            previous.calls.update(record.calls)
            previous.references.update(record.references)
            previous.exported = previous.exported or record.exported
            if record.calls or span(record.node) > span(previous.node):
                previous.node = record.node
        return list(merged.values())

    def _symbol(self, record: _DefinitionRecord, *, file_path: str, file_hash: str) -> AstSymbol:
        parent_id = f"{file_path}::{record.parent_name}" if record.parent_name else None
        symbol_name = record.name
        symbol_id = (
            f"{parent_id}.{symbol_name}"
            if parent_id is not None
            else f"{file_path}::{symbol_name}"
        )
        return AstSymbol(
            id=symbol_id,
            type=record.kind,
            name=symbol_name,
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
                "tree_sitter_query": True,
                "tree_sitter_type": record.node.type,
            },
        )


def definition_capture_name(captures: dict[str, list[Any]]) -> str | None:
    for name in captures:
        if name.startswith(DEFINITION_PREFIX) and name not in DEFINITION_META_CAPTURES:
            return name
    return None


def first_capture(captures: dict[str, list[Any]], name: str):
    items = captures.get(name) or []
    return items[0] if items else None


def nearest_container(node, containers: list[_DefinitionRecord]) -> _DefinitionRecord | None:
    candidates = [
        container
        for container in containers
        if contains(container.node, node) and container.node != node
    ]
    return min(candidates, key=lambda item: span(item.node), default=None)


def innermost_owner(node, records: list[_DefinitionRecord]) -> _DefinitionRecord | None:
    candidates = [record for record in records if contains(record.node, node)]
    return min(candidates, key=lambda item: span(item.node), default=None)


def contains(container, node) -> bool:
    return container.start_byte <= node.start_byte and node.end_byte <= container.end_byte


def span(node) -> int:
    return node.end_byte - node.start_byte


def normalize_import(value: str) -> str:
    text = value.strip().rstrip(";")
    if text.startswith(("<", '"', "'")) and text.endswith((">", '"', "'")):
        text = text[1:-1]
    return text.strip()


def normalize_identifier(value: str) -> str:
    text = value.strip().strip("&*")
    text = text.removeprefix("::")
    text = text.replace("this.", "").replace("self.", "")
    for delimiter in ("::", ".", "->"):
        if delimiter in text:
            text = text.rsplit(delimiter, 1)[-1]
    return text.strip()


def signature_text(node, language: str) -> str:
    text = node.text.decode("utf-8", errors="replace").strip()
    if "{" in text:
        return text.split("{", 1)[0].strip()
    if language == "rust" and ";" in text:
        return text.split(";", 1)[0].strip()
    return text


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
    if query_symbol is not None or symbol.metadata.get("tree_sitter_query"):
        metadata["tree_sitter_query"] = True
    return replace(symbol, metadata=metadata)
