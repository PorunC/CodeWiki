from dataclasses import replace

import tree_sitter_go

from backend.app.services.ast_parsers.base import AstSymbol
from backend.app.services.ast_parsers.common import HTTP_METHODS
from backend.app.services.ast_parsers.ecma.tree import (
    descendants_of_type,
    field_text,
    node_text,
    strip_quotes,
)
from backend.app.services.ast_parsers.query import (
    QueryLanguageSpec,
    QueryParseContext,
    TreeSitterQueryParser,
    merge_enhanced_symbols,
)


GO_TYPE_DECLARATIONS = {"type_alias", "type_spec"}


GO_QUERY = """
(import_spec
  path: (_) @import.source)

(type_spec
  name: (type_identifier) @definition.name
  type: (struct_type)) @definition.class

(type_spec
  name: (type_identifier) @definition.name
  type: (interface_type)) @definition.interface

(type_alias
  name: (type_identifier) @definition.name) @definition.schema

(function_declaration
  name: (identifier) @definition.name) @definition.function

(method_declaration
  receiver: (parameter_list
    (parameter_declaration
      type: (type_identifier) @definition.parent))
  name: (field_identifier) @definition.name) @definition.method

(method_declaration
  receiver: (parameter_list
    (parameter_declaration
      type: (pointer_type
        (type_identifier) @definition.parent)))
  name: (field_identifier) @definition.name) @definition.method

(method_elem
  name: (field_identifier) @definition.name) @definition.method

(call_expression
  function: (identifier) @call.name)

(call_expression
  function: (selector_expression
    field: (field_identifier) @call.name))

(type_identifier) @reference.name
"""


class TreeSitterGoParser(TreeSitterQueryParser):
    def __init__(self) -> None:
        super().__init__(
            QueryLanguageSpec(
                language="go",
                grammar=tree_sitter_go.language,
                query=GO_QUERY,
            )
        )

    def augment_symbols(
        self,
        symbols: list[AstSymbol],
        context: QueryParseContext,
    ) -> list[AstSymbol]:
        package_name = go_package_name(context.root, context.source)
        enhanced_symbols = go_declaration_symbols(
            context.root,
            source=context.source,
            file_path=context.file_path,
            file_hash=context.file_hash,
            package_name=package_name,
        )
        exports = sorted(
            {
                symbol.name
                for symbol in enhanced_symbols
                if symbol.type not in {"endpoint", "file"}
                and symbol.parent_id is None
                and is_exported(symbol.name)
            }
        )
        file_symbol = replace(
            symbols[0],
            imports=go_import_names(context.root, context.source),
            exports=exports,
            metadata={
                **symbols[0].metadata,
                "package": package_name,
                "language_enhancer": "go",
            },
        )
        return merge_enhanced_symbols(
            symbols,
            [file_symbol, *enhanced_symbols],
            enhancer="go",
        )


def go_package_name(root, source: bytes) -> str:
    package_clause = next((child for child in root.named_children if child.type == "package_clause"), None)
    if package_clause is None:
        return ""
    for child in package_clause.named_children:
        if child.type == "package_identifier":
            return node_text(child, source)
    return ""


def go_import_names(root, source: bytes) -> list[str]:
    imports: set[str] = set()
    for spec in descendants_of_type(root, {"import_spec"}):
        path_node = spec.child_by_field_name("path")
        if path_node is not None:
            imports.add(strip_quotes(node_text(path_node, source)))
    return sorted(imports)


def go_declaration_symbols(
    root,
    *,
    source: bytes,
    file_path: str,
    file_hash: str,
    package_name: str,
) -> list[AstSymbol]:
    symbols: list[AstSymbol] = []
    for node in root.named_children:
        if node.type == "type_declaration":
            for child in node.named_children:
                if child.type in GO_TYPE_DECLARATIONS:
                    symbols.extend(
                        go_type_symbols(
                            child,
                            source=source,
                            file_path=file_path,
                            file_hash=file_hash,
                            package_name=package_name,
                        )
                    )
        elif node.type == "function_declaration":
            symbol = go_function_symbol(
                node,
                source=source,
                file_path=file_path,
                file_hash=file_hash,
                package_name=package_name,
            )
            if symbol is not None:
                symbols.append(symbol)
        elif node.type == "method_declaration":
            symbol = go_method_symbol(
                node,
                source=source,
                file_path=file_path,
                file_hash=file_hash,
                package_name=package_name,
            )
            if symbol is not None:
                symbols.append(symbol)
    symbols.extend(
        go_endpoint_symbols(root, source=source, file_path=file_path, file_hash=file_hash)
    )
    return symbols


def go_type_symbols(
    node,
    *,
    source: bytes,
    file_path: str,
    file_hash: str,
    package_name: str,
) -> list[AstSymbol]:
    name = field_text(node, "name", source)
    if not name:
        return []
    type_node = node.child_by_field_name("type")
    symbol_id = f"{file_path}::{name}"
    symbol_type = go_symbol_type(type_node)
    symbol = AstSymbol(
        id=symbol_id,
        type=symbol_type,
        name=name,
        file_path=file_path,
        language="go",
        start_line=start_line(node),
        end_line=end_line(node),
        signature=go_signature(node, source),
        references=go_reference_names(node, source),
        hash=file_hash,
        metadata={
            "exported": is_exported(name),
            "package": package_name,
            "schema_kind": go_schema_kind(type_node),
            "tree_sitter_type": node.type,
        },
    )
    return [symbol, *go_interface_method_symbols(node, source, file_path, file_hash, symbol_id)]


def go_function_symbol(
    node,
    *,
    source: bytes,
    file_path: str,
    file_hash: str,
    package_name: str,
) -> AstSymbol | None:
    name = field_text(node, "name", source)
    if not name:
        return None
    return AstSymbol(
        id=f"{file_path}::{name}",
        type="function",
        name=name,
        file_path=file_path,
        language="go",
        start_line=start_line(node),
        end_line=end_line(node),
        signature=go_signature(node, source),
        calls=go_call_names(node, source),
        references=go_reference_names(node, source),
        hash=file_hash,
        metadata={
            "exported": is_exported(name),
            "package": package_name,
            "tree_sitter_type": node.type,
        },
    )


def go_method_symbol(
    node,
    *,
    source: bytes,
    file_path: str,
    file_hash: str,
    package_name: str,
) -> AstSymbol | None:
    name = field_text(node, "name", source)
    if not name:
        return None
    receiver = go_receiver_type(node, source)
    parent_id = f"{file_path}::{receiver}" if receiver else None
    symbol_id = f"{parent_id}.{name}" if parent_id else f"{file_path}::{name}"
    return AstSymbol(
        id=symbol_id,
        type="method",
        name=name,
        file_path=file_path,
        language="go",
        start_line=start_line(node),
        end_line=end_line(node),
        parent_id=parent_id,
        signature=go_signature(node, source),
        calls=go_call_names(node, source),
        references=go_reference_names(node, source),
        hash=file_hash,
        metadata={
            "exported": is_exported(name),
            "package": package_name,
            "receiver": receiver,
            "tree_sitter_type": node.type,
        },
    )


def go_interface_method_symbols(
    node,
    source: bytes,
    file_path: str,
    file_hash: str,
    parent_id: str,
) -> list[AstSymbol]:
    type_node = node.child_by_field_name("type")
    if type_node is None or type_node.type != "interface_type":
        return []
    symbols: list[AstSymbol] = []
    for method in descendants_of_type(type_node, {"method_elem"}):
        name = field_text(method, "name", source)
        if not name:
            continue
        symbols.append(
            AstSymbol(
                id=f"{parent_id}.{name}",
                type="method",
                name=name,
                file_path=file_path,
                language="go",
                start_line=start_line(method),
                end_line=end_line(method),
                parent_id=parent_id,
                signature=node_text(method, source).strip(),
                references=go_reference_names(method, source),
                hash=file_hash,
                metadata={"exported": is_exported(name), "tree_sitter_type": method.type},
            )
        )
    return symbols


def go_endpoint_symbols(root, *, source: bytes, file_path: str, file_hash: str) -> list[AstSymbol]:
    symbols: list[AstSymbol] = []
    for call in descendants_of_type(root, {"call_expression"}):
        function_node = call.child_by_field_name("function")
        if function_node is None or function_node.type != "selector_expression":
            continue
        route_method = go_selector_field(function_node, source)
        if route_method.lower() not in HTTP_METHODS:
            continue
        route_path, handler = go_route_arguments(call, source)
        if not route_path:
            continue
        method = route_method.upper()
        route_line = start_line(call)
        symbols.append(
            AstSymbol(
                id=f"{file_path}::endpoint:{method}:{route_path}:{route_line}",
                type="endpoint",
                name=f"{method} {route_path}",
                file_path=file_path,
                language="go",
                start_line=route_line,
                end_line=end_line(call),
                calls=[handler] if handler else [],
                hash=file_hash,
                metadata={
                    "handler": handler,
                    "route_method": method,
                    "route_path": route_path,
                    "tree_sitter_type": call.type,
                },
            )
        )
    return symbols


def go_route_arguments(call, source: bytes) -> tuple[str | None, str | None]:
    arguments = call.child_by_field_name("arguments")
    if arguments is None:
        return None, None
    named = arguments.named_children
    if not named:
        return None, None
    first = named[0]
    if first.type not in {"interpreted_string_literal", "raw_string_literal"}:
        return None, None
    route_path = strip_quotes(node_text(first, source))
    handler = go_expression_name(named[1], source) if len(named) > 1 else None
    return route_path, handler


def go_symbol_type(type_node) -> str:
    if type_node is None:
        return "schema"
    if type_node.type == "struct_type":
        return "class"
    if type_node.type == "interface_type":
        return "interface"
    return "schema"


def go_schema_kind(type_node) -> str | None:
    if type_node is None:
        return None
    if type_node.type in {"struct_type", "interface_type"}:
        return None
    return type_node.type


def go_receiver_type(node, source: bytes) -> str | None:
    receiver = node.child_by_field_name("receiver")
    if receiver is None:
        return None
    type_names = [
        node_text(child, source)
        for child in descendants_of_type(receiver, {"qualified_type", "type_identifier"})
    ]
    if not type_names:
        return None
    return type_names[-1].rsplit(".", 1)[-1]


def go_call_names(node, source: bytes) -> list[str]:
    calls: set[str] = set()
    for call in descendants_of_type(node, {"call_expression"}):
        function_node = call.child_by_field_name("function")
        if function_node is None:
            continue
        name = go_expression_name(function_node, source)
        if name:
            calls.add(name)
    return sorted(calls)


def go_reference_names(node, source: bytes) -> list[str]:
    references: set[str] = set()
    for descendant in descendants_of_type(
        node,
        {
            "field_identifier",
            "identifier",
            "package_identifier",
            "qualified_type",
            "type_identifier",
        },
    ):
        text = node_text(descendant, source).strip()
        if text:
            references.add(text.rsplit(".", 1)[-1])
    return sorted(references)


def go_expression_name(node, source: bytes) -> str:
    if node.type == "selector_expression":
        return go_selector_field(node, source)
    text = node_text(node, source).strip()
    return text.rsplit(".", 1)[-1]


def go_selector_field(node, source: bytes) -> str:
    field = node.child_by_field_name("field")
    return node_text(field, source).strip() if field is not None else ""


def go_signature(node, source: bytes) -> str:
    text = node_text(node, source).strip()
    if "{" in text:
        return text.split("{", 1)[0].strip()
    return text


def is_exported(name: str) -> bool:
    return bool(name[:1].isupper())


def start_line(node) -> int:
    return node.start_point.row + 1


def end_line(node) -> int:
    return node.end_point.row + 1
