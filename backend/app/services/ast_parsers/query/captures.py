from typing import Any

from tree_sitter import Query, QueryCursor

from backend.app.services.ast_parsers.query.models import DefinitionRecord
from backend.app.services.ast_parsers.query.normalization import (
    normalize_identifier,
    normalize_import,
)
from backend.app.services.ast_parsers.query.topology import (
    innermost_owner,
    nearest_container,
    span,
)
from backend.app.services.ast_parsers.tree import node_text

DEFINITION_PREFIX = "definition."
DEFINITION_META_CAPTURES = {"definition.name", "definition.parent", "definition.exported"}


def records_from_query(
    query: Query,
    root,
    source: bytes,
) -> tuple[list[DefinitionRecord], list[str]]:
    records: list[DefinitionRecord] = []
    imports: set[str] = set()
    cursor = QueryCursor(query)
    for _, captures in cursor.matches(root):
        for import_node in captures.get("import.source", []):
            value = normalize_import(node_text(import_node, source))
            if value:
                imports.add(value)

        definition_capture = definition_capture_name(captures)
        if definition_capture is None:
            continue
        name_node = first_capture(captures, "definition.name")
        if name_node is None:
            continue
        name = normalize_identifier(node_text(name_node, source))
        if not name:
            continue
        parent_node = first_capture(captures, "definition.parent")
        parent_name = normalize_identifier(node_text(parent_node, source)) if parent_node else ""
        record = DefinitionRecord(
            kind=definition_capture.removeprefix(DEFINITION_PREFIX),
            node=captures[definition_capture][0],
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


def assign_containment_parents(records: list[DefinitionRecord]) -> None:
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


def assign_calls(
    query: Query,
    root,
    source: bytes,
    records: list[DefinitionRecord],
) -> None:
    if not records:
        return
    cursor = QueryCursor(query)
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


def merge_records(records: list[DefinitionRecord]) -> list[DefinitionRecord]:
    merged: dict[tuple[str, str, str], DefinitionRecord] = {}
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


def definition_capture_name(captures: dict[str, list[Any]]) -> str | None:
    for name in captures:
        if name.startswith(DEFINITION_PREFIX) and name not in DEFINITION_META_CAPTURES:
            return name
    return None


def first_capture(captures: dict[str, list[Any]], name: str):
    items = captures.get(name) or []
    return items[0] if items else None
