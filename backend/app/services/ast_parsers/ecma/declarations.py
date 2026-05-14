from backend.app.services.ast_parsers.base import AstSymbol
from backend.app.services.ast_parsers.ecma.tree import (
    descendants_of_type,
    end_line,
    field_text,
    first_named_child,
    node_text,
    start_line,
)
from backend.app.services.ast_parsers.ecma.schemas import schema_symbol


def declaration_symbols(
    *,
    root,
    source: bytes,
    file_path: str,
    file_hash: str,
    language: str,
    exported_names: set[str],
) -> list[AstSymbol]:
    symbols: list[AstSymbol] = []
    for node in root.named_children:
        exported = node.type == "export_statement"
        if exported:
            exported_names.update(exported_names_from_statement(node, source))
        declaration = node.child_by_field_name("declaration") if exported else node
        if declaration is None and exported:
            declaration = first_named_child(node)
        if declaration is None:
            continue
        extracted = symbol_from_declaration(
            declaration,
            source=source,
            file_path=file_path,
            file_hash=file_hash,
            language=language,
            parent_id=None,
            exported=exported,
        )
        symbols.extend(extracted)
        for symbol in extracted:
            if exported and symbol.type != "method":
                exported_names.add(symbol.name)
    return symbols


def symbol_from_declaration(
    node,
    *,
    source: bytes,
    file_path: str,
    file_hash: str,
    language: str,
    parent_id: str | None,
    exported: bool,
) -> list[AstSymbol]:
    if node.type == "class_declaration":
        return class_symbols(
            node,
            source=source,
            file_path=file_path,
            file_hash=file_hash,
            language=language,
            parent_id=parent_id,
            exported=exported,
        )
    if node.type in {"interface_declaration", "type_alias_declaration", "enum_declaration"}:
        return [
            schema_symbol(
                node,
                source=source,
                file_path=file_path,
                file_hash=file_hash,
                language=language,
                exported=exported,
            )
        ]
    if node.type == "function_declaration":
        name = field_text(node, "name", source)
        if not name:
            return []
        return [
            AstSymbol(
                id=f"{file_path}::{name}",
                type="function",
                name=name,
                file_path=file_path,
                language=language,
                start_line=start_line(node),
                end_line=end_line(node),
                parent_id=parent_id,
                signature=node_text(node, source).split("{", 1)[0].strip(),
                calls=call_names(node, source),
                references=reference_names(node, source),
                hash=file_hash,
                metadata={"exported": exported, "tree_sitter_type": node.type},
            )
        ]
    if node.type == "lexical_declaration":
        return lexical_function_symbols(
            node,
            source=source,
            file_path=file_path,
            file_hash=file_hash,
            language=language,
            parent_id=parent_id,
            exported=exported,
        )
    return []


def lexical_function_symbols(
    node,
    *,
    source: bytes,
    file_path: str,
    file_hash: str,
    language: str,
    parent_id: str | None,
    exported: bool,
) -> list[AstSymbol]:
    symbols: list[AstSymbol] = []
    for declarator in descendants_of_type(node, {"variable_declarator"}):
        name = field_text(declarator, "name", source)
        value = declarator.child_by_field_name("value")
        if not name or value is None:
            continue
        if value.type in {"arrow_function", "function", "function_expression"}:
            symbols.append(
                AstSymbol(
                    id=f"{file_path}::{name}",
                    type="function",
                    name=name,
                    file_path=file_path,
                    language=language,
                    start_line=start_line(declarator),
                    end_line=end_line(declarator),
                    parent_id=parent_id,
                    signature=node_text(declarator, source).split("=>", 1)[0].strip(),
                    calls=call_names(value, source),
                    references=reference_names(declarator, source),
                    hash=file_hash,
                    metadata={"exported": exported, "tree_sitter_type": value.type},
                )
            )
    return symbols


def class_symbols(
    node,
    *,
    source: bytes,
    file_path: str,
    file_hash: str,
    language: str,
    parent_id: str | None,
    exported: bool,
) -> list[AstSymbol]:
    name = field_text(node, "name", source)
    if not name:
        return []
    symbol_id = f"{file_path}::{name}"
    bases, implements = class_heritage(node, source)
    symbols = [
        AstSymbol(
            id=symbol_id,
            type="class",
            name=name,
            file_path=file_path,
            language=language,
            start_line=start_line(node),
            end_line=end_line(node),
            parent_id=parent_id,
            signature=node_text(node, source).split("{", 1)[0].strip(),
            bases=bases,
            implements=implements,
            calls=call_names(node, source),
            references=reference_names(node, source),
            hash=file_hash,
            metadata={"exported": exported, "tree_sitter_type": node.type},
        )
    ]
    body = node.child_by_field_name("body")
    if body is not None:
        for method in body.named_children:
            if method.type != "method_definition":
                continue
            method_name = field_text(method, "name", source)
            if not method_name:
                continue
            symbols.append(
                AstSymbol(
                    id=f"{file_path}::{name}.{method_name}",
                    type="method",
                    name=method_name,
                    file_path=file_path,
                    language=language,
                    start_line=start_line(method),
                    end_line=end_line(method),
                    parent_id=symbol_id,
                    signature=node_text(method, source).split("{", 1)[0].strip(),
                    calls=call_names(method, source),
                    references=reference_names(method, source),
                    hash=file_hash,
                    metadata={"tree_sitter_type": method.type},
                )
            )
    return symbols


def call_names(node, source: bytes) -> list[str]:
    calls: set[str] = set()
    for call in descendants_of_type(node, {"call_expression"}):
        function_node = call.child_by_field_name("function")
        if function_node is None:
            continue
        text = node_text(function_node, source)
        if "." in text:
            calls.add(text.rsplit(".", 1)[-1])
        elif text and text not in {"require"}:
            calls.add(text)
    return sorted(calls)


def reference_names(node, source: bytes) -> list[str]:
    references: set[str] = set()
    for descendant in descendants_of_type(
        node,
        {
            "identifier",
            "nested_type_identifier",
            "property_identifier",
            "shorthand_property_identifier",
            "type_identifier",
        },
    ):
        text = node_text(descendant, source).strip()
        if text:
            references.add(text.rsplit(".", 1)[-1])
    return sorted(references)


def class_heritage(node, source: bytes) -> tuple[list[str], list[str]]:
    bases: list[str] = []
    implements: list[str] = []
    heritage = next((child for child in node.named_children if child.type == "class_heritage"), None)
    if heritage is None:
        return bases, implements
    for child in heritage.named_children:
        if child.type == "extends_clause":
            bases.extend(heritage_type_names(child, source))
        elif child.type == "implements_clause":
            implements.extend(heritage_type_names(child, source))
    return sorted(set(bases)), sorted(set(implements))


def heritage_type_names(node, source: bytes) -> list[str]:
    names: list[str] = []
    for descendant in node.named_children:
        if descendant.type in {"identifier", "type_identifier", "nested_type_identifier"}:
            names.append(node_text(descendant, source))
        else:
            names.extend(heritage_type_names(descendant, source))
    return names


def exported_names_from_statement(node, source: bytes) -> set[str]:
    names: set[str] = set()
    for specifier in descendants_of_type(node, {"export_specifier"}):
        alias = field_text(specifier, "alias", source)
        name = field_text(specifier, "name", source)
        exported_name = alias or name
        if exported_name:
            names.add(exported_name)
            continue
        identifiers = [
            node_text(child, source)
            for child in specifier.named_children
            if child.type in {"identifier", "type_identifier"}
        ]
        if identifiers:
            names.add(identifiers[-1])
    return names
