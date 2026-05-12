import ast as py_ast
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from tree_sitter import Language, Parser
import tree_sitter_javascript
import tree_sitter_typescript

from backend.app.services.language_detector import LanguageDetector


HTTP_METHODS = {"get", "post", "put", "patch", "delete", "options", "head"}


@dataclass(frozen=True)
class AstSymbol:
    id: str
    type: str
    name: str
    file_path: str
    language: str
    start_line: int
    end_line: int
    parent_id: str | None = None
    signature: str | None = None
    docstring: str | None = None
    imports: list[str] = field(default_factory=list)
    exports: list[str] = field(default_factory=list)
    bases: list[str] = field(default_factory=list)
    decorators: list[str] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)
    hash: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class LanguageParser(Protocol):
    language: str

    def parse(self, path: Path, *, repo_root: Path | None = None) -> list[AstSymbol]:
        ...


class AstParserRegistry:
    def __init__(self) -> None:
        self._parsers: dict[str, LanguageParser] = {}

    @classmethod
    def default(cls) -> "AstParserRegistry":
        registry = cls()
        registry.register(PythonAstParser())
        registry.register(TreeSitterTypeScriptParser("typescript"))
        registry.register(TreeSitterTypeScriptParser("tsx"))
        registry.register(TreeSitterJavaScriptParser("javascript"))
        registry.register(TreeSitterJavaScriptParser("jsx"))
        return registry

    def register(self, parser: LanguageParser) -> None:
        self._parsers[parser.language] = parser

    def get(self, language: str) -> LanguageParser | None:
        return self._parsers.get(language)

    def supported_languages(self) -> list[str]:
        return sorted(self._parsers)


class AstParser:
    def __init__(
        self,
        *,
        registry: AstParserRegistry | None = None,
        language_detector: LanguageDetector | None = None,
    ) -> None:
        self.registry = registry or AstParserRegistry.default()
        self.language_detector = language_detector or LanguageDetector()

    def parse_file(
        self,
        path: Path,
        *,
        repo_root: Path | None = None,
        language: str | None = None,
    ) -> list[AstSymbol]:
        detected_language = language or self.language_detector.detect(path)
        parser = self.registry.get(detected_language)
        if parser is None:
            return []
        return parser.parse(path, repo_root=repo_root)


class PythonAstParser:
    language = "python"

    def parse(self, path: Path, *, repo_root: Path | None = None) -> list[AstSymbol]:
        content = path.read_text(encoding="utf-8", errors="replace")
        file_path = _relative_path(path, repo_root)
        file_hash = _content_hash(content)
        lines = content.splitlines()
        tree = py_ast.parse(content, filename=str(path))
        imports = _python_imports(tree)

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
                exports=_python_exports(tree),
                hash=file_hash,
            )
        ]

        visitor = _PythonSymbolVisitor(file_path=file_path, file_hash=file_hash, lines=lines)
        visitor.visit(tree)
        symbols.extend(visitor.symbols)
        return symbols


class _PythonSymbolVisitor(py_ast.NodeVisitor):
    def __init__(self, *, file_path: str, file_hash: str, lines: list[str]) -> None:
        self.file_path = file_path
        self.file_hash = file_hash
        self.lines = lines
        self.class_stack: list[str] = []
        self.symbols: list[AstSymbol] = []

    def visit_ClassDef(self, node: py_ast.ClassDef) -> None:
        qualname = ".".join([*self.class_stack, node.name])
        symbol_id = f"{self.file_path}::{qualname}"
        parent_id = f"{self.file_path}::{'.'.join(self.class_stack)}" if self.class_stack else None
        decorators = [_python_expr_name(item) for item in node.decorator_list]
        bases = [_python_expr_name(item) for item in node.bases]
        symbol_type = "schema" if _is_python_schema_class(node, bases, decorators) else "class"
        self.symbols.append(
            AstSymbol(
                id=symbol_id,
                type=symbol_type,
                name=node.name,
                file_path=self.file_path,
                language="python",
                start_line=node.lineno,
                end_line=getattr(node, "end_lineno", node.lineno),
                parent_id=parent_id,
                docstring=py_ast.get_docstring(node),
                bases=bases,
                decorators=decorators,
                calls=_python_calls(node),
                hash=self.file_hash,
                metadata={"python_node_type": "ClassDef"},
            )
        )
        self.class_stack.append(node.name)
        self.generic_visit(node)
        self.class_stack.pop()

    def visit_FunctionDef(self, node: py_ast.FunctionDef) -> None:
        self._add_function(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: py_ast.AsyncFunctionDef) -> None:
        self._add_function(node)
        self.generic_visit(node)

    def _add_function(self, node: py_ast.FunctionDef | py_ast.AsyncFunctionDef) -> None:
        qualname = ".".join([*self.class_stack, node.name])
        symbol_id = f"{self.file_path}::{qualname}"
        parent_id = f"{self.file_path}::{'.'.join(self.class_stack)}" if self.class_stack else None
        decorators = [_python_expr_name(item) for item in node.decorator_list]
        calls = _python_calls(node)
        self.symbols.append(
            AstSymbol(
                id=symbol_id,
                type="method" if self.class_stack else "function",
                name=node.name,
                file_path=self.file_path,
                language="python",
                start_line=node.lineno,
                end_line=getattr(node, "end_lineno", node.lineno),
                parent_id=parent_id,
                signature=_signature_line(self.lines, node.lineno),
                docstring=py_ast.get_docstring(node),
                decorators=decorators,
                calls=calls,
                hash=self.file_hash,
                metadata={"python_node_type": type(node).__name__},
            )
        )
        for route in _python_endpoint_decorators(node):
            method = route["method"]
            route_path = route["path"]
            endpoint_id = f"{self.file_path}::endpoint:{method}:{route_path}:{qualname}"
            self.symbols.append(
                AstSymbol(
                    id=endpoint_id,
                    type="endpoint",
                    name=f"{method} {route_path}",
                    file_path=self.file_path,
                    language="python",
                    start_line=node.decorator_list[0].lineno if node.decorator_list else node.lineno,
                    end_line=getattr(node, "end_lineno", node.lineno),
                    parent_id=None,
                    calls=[node.name],
                    hash=self.file_hash,
                    metadata={
                        "route_method": method,
                        "route_path": route_path,
                        "handler": node.name,
                        "framework_hint": route["object"],
                    },
                )
            )


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
        file_path = _relative_path(path, repo_root)
        file_hash = _content_hash(content)
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
        for node in _descendants_of_type(root, {"import_statement"}):
            string_node = _first_descendant_of_type(node, {"string"})
            if string_node is not None:
                imports.add(_strip_quotes(_node_text(string_node, source)))
        for node in _descendants_of_type(root, {"call_expression"}):
            function_node = node.child_by_field_name("function")
            if function_node is None or _node_text(function_node, source) != "require":
                continue
            arguments = node.child_by_field_name("arguments")
            string_node = _first_descendant_of_type(arguments, {"string"}) if arguments else None
            if string_node is not None:
                imports.add(_strip_quotes(_node_text(string_node, source)))
        return sorted(imports)


def _python_imports(tree: py_ast.AST) -> list[str]:
    imports: list[str] = []
    for node in py_ast.walk(tree):
        if isinstance(node, py_ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, py_ast.ImportFrom):
            prefix = "." * node.level
            module = node.module or ""
            if node.level:
                imports.append(f"{prefix}{module}")
            else:
                imports.extend(f"{module}.{alias.name}".strip(".") for alias in node.names)
    return sorted(set(item for item in imports if item))


def _python_exports(tree: py_ast.AST) -> list[str]:
    for node in py_ast.walk(tree):
        if isinstance(node, py_ast.Assign):
            for target in node.targets:
                if isinstance(target, py_ast.Name) and target.id == "__all__":
                    if isinstance(node.value, (py_ast.List, py_ast.Tuple)):
                        return [
                            item.value
                            for item in node.value.elts
                            if isinstance(item, py_ast.Constant) and isinstance(item.value, str)
                        ]
    return []


def _python_calls(node: py_ast.AST) -> list[str]:
    calls: set[str] = set()
    for child in py_ast.walk(node):
        if isinstance(child, py_ast.Call):
            if isinstance(child.func, py_ast.Name):
                calls.add(child.func.id)
            elif isinstance(child.func, py_ast.Attribute):
                calls.add(child.func.attr)
    return sorted(calls)


def _python_endpoint_decorators(node: py_ast.FunctionDef | py_ast.AsyncFunctionDef) -> list[dict[str, str]]:
    endpoints: list[dict[str, str]] = []
    for decorator in node.decorator_list:
        if not isinstance(decorator, py_ast.Call) or not isinstance(decorator.func, py_ast.Attribute):
            continue
        method = decorator.func.attr.lower()
        if method not in HTTP_METHODS:
            continue
        route_object = _python_expr_name(decorator.func.value)
        if route_object not in {"app", "router", "api", "bp", "blueprint"}:
            continue
        if not decorator.args:
            continue
        first_arg = decorator.args[0]
        if isinstance(first_arg, py_ast.Constant) and isinstance(first_arg.value, str):
            endpoints.append({"method": method.upper(), "path": first_arg.value, "object": route_object})
    return endpoints


def _is_python_schema_class(node: py_ast.ClassDef, bases: list[str], decorators: list[str]) -> bool:
    if any(base.endswith(("BaseModel", "TypedDict", "Schema", "Serializer")) for base in bases):
        return True
    return any(decorator.endswith("dataclass") for decorator in decorators)


def _python_expr_name(node: py_ast.AST) -> str:
    if isinstance(node, py_ast.Name):
        return node.id
    if isinstance(node, py_ast.Attribute):
        base = _python_expr_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    if isinstance(node, py_ast.Call):
        return _python_expr_name(node.func)
    if isinstance(node, py_ast.Subscript):
        return _python_expr_name(node.value)
    return ""


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
    handler = _node_text(args[1], source) if len(args) > 1 and args[1].type == "identifier" else ""
    return {"object": route_object, "method": method.upper(), "path": _strip_quotes(_node_text(args[0], source)), "handler": handler}


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


def _signature_line(lines: list[str], line_number: int) -> str | None:
    if line_number < 1 or line_number > len(lines):
        return None
    return lines[line_number - 1].strip().rstrip(":")


def _relative_path(path: Path, repo_root: Path | None) -> str:
    if repo_root is None:
        return path.name
    return path.resolve().relative_to(repo_root.resolve()).as_posix()


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()
