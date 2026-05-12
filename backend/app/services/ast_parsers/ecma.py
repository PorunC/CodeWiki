from pathlib import Path

from tree_sitter import Language, Parser
import tree_sitter_javascript
import tree_sitter_typescript

from backend.app.services.ast_parsers.base import AstSymbol
from backend.app.services.ast_parsers.common import HTTP_METHODS, content_hash, relative_path


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
        return _TreeSitterEcmaParser(self.language, self.parser).parse(path, repo_root=repo_root)


class TreeSitterJavaScriptParser:
    def __init__(self, language: str) -> None:
        self.language = language
        self.parser = Parser(Language(tree_sitter_javascript.language()))

    def parse(self, path: Path, *, repo_root: Path | None = None) -> list[AstSymbol]:
        return _TreeSitterEcmaParser(self.language, self.parser).parse(path, repo_root=repo_root)


class _TreeSitterEcmaParser:
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
        imports = self._imports(root, source)
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
            self._declaration_symbols(
                root=root,
                source=source,
                file_path=file_path,
                file_hash=file_hash,
                exported_names=exported_names,
            )
        )
        symbols[0] = AstSymbol(
            **{
                **symbols[0].__dict__,
                "exports": sorted(exported_names),
            }
        )
        symbols.extend(self._endpoint_symbols(root, source, file_path=file_path, file_hash=file_hash))
        return symbols

    def _declaration_symbols(
        self,
        *,
        root,
        source: bytes,
        file_path: str,
        file_hash: str,
        exported_names: set[str],
    ) -> list[AstSymbol]:
        symbols: list[AstSymbol] = []
        for node in root.named_children:
            exported = node.type == "export_statement"
            if exported:
                exported_names.update(_exported_names_from_statement(node, source))
            declaration = node.child_by_field_name("declaration") if exported else node
            if declaration is None and exported:
                declaration = _first_named_child(node)
            if declaration is None:
                continue
            extracted = self._symbol_from_declaration(
                declaration,
                source=source,
                file_path=file_path,
                file_hash=file_hash,
                parent_id=None,
                exported=exported,
            )
            symbols.extend(extracted)
            for symbol in extracted:
                if exported and symbol.type != "method":
                    exported_names.add(symbol.name)
        return symbols

    def _symbol_from_declaration(
        self,
        node,
        *,
        source: bytes,
        file_path: str,
        file_hash: str,
        parent_id: str | None,
        exported: bool,
    ) -> list[AstSymbol]:
        if node.type == "class_declaration":
            return self._class_symbols(
                node,
                source=source,
                file_path=file_path,
                file_hash=file_hash,
                parent_id=parent_id,
                exported=exported,
            )
        if node.type in {"interface_declaration", "type_alias_declaration", "enum_declaration"}:
            return [
                self._schema_symbol(
                    node,
                    source=source,
                    file_path=file_path,
                    file_hash=file_hash,
                    exported=exported,
                )
            ]
        if node.type == "function_declaration":
            name = _field_text(node, "name", source)
            if not name:
                return []
            return [
                AstSymbol(
                    id=f"{file_path}::{name}",
                    type="function",
                    name=name,
                    file_path=file_path,
                    language=self.language,
                    start_line=_start_line(node),
                    end_line=_end_line(node),
                    parent_id=parent_id,
                    signature=_node_text(node, source).split("{", 1)[0].strip(),
                    calls=_call_names(node, source),
                    hash=file_hash,
                    metadata={"exported": exported, "tree_sitter_type": node.type},
                )
            ]
        if node.type == "lexical_declaration":
            symbols: list[AstSymbol] = []
            for declarator in _descendants_of_type(node, {"variable_declarator"}):
                name = _field_text(declarator, "name", source)
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
                            language=self.language,
                            start_line=_start_line(declarator),
                            end_line=_end_line(declarator),
                            parent_id=parent_id,
                            signature=_node_text(declarator, source).split("=>", 1)[0].strip(),
                            calls=_call_names(value, source),
                            hash=file_hash,
                            metadata={"exported": exported, "tree_sitter_type": value.type},
                        )
                    )
            return symbols
        return []

    def _class_symbols(
        self,
        node,
        *,
        source: bytes,
        file_path: str,
        file_hash: str,
        parent_id: str | None,
        exported: bool,
    ) -> list[AstSymbol]:
        name = _field_text(node, "name", source)
        if not name:
            return []
        symbol_id = f"{file_path}::{name}"
        bases = _class_bases(node, source)
        symbols = [
            AstSymbol(
                id=symbol_id,
                type="class",
                name=name,
                file_path=file_path,
                language=self.language,
                start_line=_start_line(node),
                end_line=_end_line(node),
                parent_id=parent_id,
                signature=_node_text(node, source).split("{", 1)[0].strip(),
                bases=bases,
                calls=_call_names(node, source),
                hash=file_hash,
                metadata={"exported": exported, "tree_sitter_type": node.type},
            )
        ]
        body = node.child_by_field_name("body")
        if body is not None:
            for method in body.named_children:
                if method.type != "method_definition":
                    continue
                method_name = _field_text(method, "name", source)
                if not method_name:
                    continue
                symbols.append(
                    AstSymbol(
                        id=f"{file_path}::{name}.{method_name}",
                        type="method",
                        name=method_name,
                        file_path=file_path,
                        language=self.language,
                        start_line=_start_line(method),
                        end_line=_end_line(method),
                        parent_id=symbol_id,
                        signature=_node_text(method, source).split("{", 1)[0].strip(),
                        calls=_call_names(method, source),
                        hash=file_hash,
                        metadata={"tree_sitter_type": method.type},
                    )
                )
        return symbols

    def _schema_symbol(self, node, *, source: bytes, file_path: str, file_hash: str, exported: bool) -> AstSymbol:
        name = _field_text(node, "name", source) or "anonymous_schema"
        return AstSymbol(
            id=f"{file_path}::{name}",
            type="schema",
            name=name,
            file_path=file_path,
            language=self.language,
            start_line=_start_line(node),
            end_line=_end_line(node),
            signature=_node_text(node, source).split("{", 1)[0].strip(),
            hash=file_hash,
            metadata={
                "exported": exported,
                "schema_kind": node.type.removesuffix("_declaration"),
                "fields": _schema_fields(node, source),
                "tree_sitter_type": node.type,
            },
        )

    def _endpoint_symbols(self, root, source: bytes, *, file_path: str, file_hash: str) -> list[AstSymbol]:
        endpoints: list[AstSymbol] = []
        for call in _descendants_of_type(root, {"call_expression"}):
            route = _route_call(call, source)
            if route is None:
                continue
            endpoint_id = f"{file_path}::endpoint:{route['method']}:{route['path']}:{_start_line(call)}"
            endpoints.append(
                AstSymbol(
                    id=endpoint_id,
                    type="endpoint",
                    name=f"{route['method']} {route['path']}",
                    file_path=file_path,
                    language=self.language,
                    start_line=_start_line(call),
                    end_line=_end_line(call),
                    calls=[route["handler"]] if route.get("handler") else [],
                    hash=file_hash,
                    metadata={
                        "route_method": route["method"],
                        "route_path": route["path"],
                        "handler": route.get("handler"),
                        "framework_hint": route["object"],
                        "tree_sitter_type": call.type,
                    },
                )
            )
        return endpoints

    def _imports(self, root, source: bytes) -> list[str]:
        imports: set[str] = set()
        for node in _descendants_of_type(root, {"import_statement", "export_statement"}):
            string_node = node.child_by_field_name("source")
            if string_node is None and node.type == "import_statement":
                string_node = _first_descendant_of_type(node, {"string"})
            if string_node is None and node.type == "export_statement" and " from " in _node_text(node, source):
                string_node = _first_descendant_of_type(node, {"string"})
            if string_node is not None:
                imports.add(_strip_quotes(_node_text(string_node, source)))
        for node in _descendants_of_type(root, {"call_expression"}):
            function_node = node.child_by_field_name("function")
            if function_node is None or _node_text(function_node, source) not in {"require", "import"}:
                continue
            arguments = node.child_by_field_name("arguments")
            string_node = _first_descendant_of_type(arguments, {"string"}) if arguments else None
            if string_node is not None:
                imports.add(_strip_quotes(_node_text(string_node, source)))
        return sorted(imports)


def _call_names(node, source: bytes) -> list[str]:
    calls: set[str] = set()
    for call in _descendants_of_type(node, {"call_expression"}):
        function_node = call.child_by_field_name("function")
        if function_node is None:
            continue
        text = _node_text(function_node, source)
        if "." in text:
            calls.add(text.rsplit(".", 1)[-1])
        elif text and text not in {"require"}:
            calls.add(text)
    return sorted(calls)


def _class_bases(node, source: bytes) -> list[str]:
    bases: list[str] = []
    heritage = next((child for child in node.named_children if child.type == "class_heritage"), None)
    if heritage is None:
        return bases
    for child in heritage.named_children:
        if child.type in {"extends_clause", "implements_clause"}:
            for descendant in child.named_children:
                if descendant.type in {"identifier", "type_identifier", "nested_type_identifier"}:
                    bases.append(_node_text(descendant, source))
    return bases


def _schema_fields(node, source: bytes) -> list[str]:
    body = node.child_by_field_name("body")
    if body is None:
        return []
    fields: list[str] = []
    for child in body.named_children:
        if child.type not in {"property_signature", "public_field_definition"}:
            continue
        name = _field_text(child, "name", source)
        if name:
            fields.append(name)
        else:
            identifier = _first_descendant_of_type(child, {"property_identifier", "identifier"})
            if identifier is not None:
                fields.append(_node_text(identifier, source))
    return fields


def _exported_names_from_statement(node, source: bytes) -> set[str]:
    names: set[str] = set()
    for specifier in _descendants_of_type(node, {"export_specifier"}):
        alias = _field_text(specifier, "alias", source)
        name = _field_text(specifier, "name", source)
        exported_name = alias or name
        if exported_name:
            names.add(exported_name)
            continue
        identifiers = [
            _node_text(child, source)
            for child in specifier.named_children
            if child.type in {"identifier", "type_identifier"}
        ]
        if identifiers:
            names.add(identifiers[-1])
    return names


def _route_call(node, source: bytes) -> dict[str, str] | None:
    function_node = node.child_by_field_name("function")
    if function_node is None or function_node.type != "member_expression":
        return None
    object_node = function_node.child_by_field_name("object")
    property_node = function_node.child_by_field_name("property")
    if object_node is None or property_node is None:
        return None
    route_object = _node_text(object_node, source)
    method = _node_text(property_node, source).lower()
    if route_object not in {"app", "router", "api"} or method not in HTTP_METHODS:
        return None
    arguments = node.child_by_field_name("arguments")
    if arguments is None:
        return None
    args = [child for child in arguments.named_children]
    if not args or args[0].type != "string":
        return None
    handler = _route_handler_name(args[1], source) if len(args) > 1 else ""
    return {"object": route_object, "method": method.upper(), "path": _strip_quotes(_node_text(args[0], source)), "handler": handler}


def _route_handler_name(node, source: bytes) -> str:
    if node.type == "identifier":
        return _node_text(node, source)
    if node.type == "member_expression":
        property_node = node.child_by_field_name("property")
        if property_node is not None:
            return _node_text(property_node, source)
    return ""


def _descendants_of_type(node, types: set[str]):
    stack = [node]
    while stack:
        current = stack.pop()
        if current.type in types:
            yield current
        stack.extend(reversed(current.named_children))


def _first_descendant_of_type(node, types: set[str]):
    if node is None:
        return None
    return next(_descendants_of_type(node, types), None)


def _first_named_child(node):
    return node.named_children[0] if node.named_children else None


def _field_text(node, field: str, source: bytes) -> str:
    child = node.child_by_field_name(field)
    return _node_text(child, source) if child is not None else ""


def _node_text(node, source: bytes) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] in {"'", '"', "`"} and value[-1] == value[0]:
        return value[1:-1]
    return value


def _start_line(node) -> int:
    return node.start_point.row + 1


def _end_line(node) -> int:
    return node.end_point.row + 1
