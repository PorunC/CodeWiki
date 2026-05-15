import ast as py_ast
from dataclasses import replace

import tree_sitter_python

from backend.app.services.ast_parsers.base import AstSymbol
from backend.app.services.ast_parsers.common import HTTP_METHODS
from backend.app.services.ast_parsers.query import (
    QueryLanguageSpec,
    QueryParseContext,
    TreeSitterQueryParser,
    merge_enhanced_symbols,
)


PYTHON_QUERY = """
(import_statement
  (dotted_name) @import.source)

(import_from_statement
  module_name: (dotted_name) @import.source)

(class_definition
  name: (identifier) @definition.name
  superclasses: (argument_list
    (identifier) @heritage.base)?) @definition.class

(function_definition
  name: (identifier) @definition.name) @definition.function

(call
  function: (identifier) @call.name)

(call
  function: (attribute
    attribute: (identifier) @call.name))

(identifier) @reference.name
"""


class PythonAstParser(TreeSitterQueryParser):
    def __init__(self) -> None:
        super().__init__(
            QueryLanguageSpec(
                language="python",
                grammar=tree_sitter_python.language,
                query=PYTHON_QUERY,
            )
        )

    def augment_symbols(
        self,
        symbols: list[AstSymbol],
        context: QueryParseContext,
    ) -> list[AstSymbol]:
        tree = py_ast.parse(context.content, filename=str(context.path))
        file_symbol = replace(
            symbols[0],
            imports=_python_imports(tree),
            exports=_python_exports(tree),
            metadata={
                **symbols[0].metadata,
                "language_enhancer": "python",
            },
        )
        visitor = _PythonSymbolVisitor(
            file_path=context.file_path,
            file_hash=context.file_hash,
            lines=context.lines,
        )
        visitor.visit(tree)
        return merge_enhanced_symbols(
            symbols,
            [file_symbol, *visitor.symbols],
            enhancer="python",
        )


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
                references=_python_references(node),
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
                references=_python_references(node),
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


def _python_references(node: py_ast.AST) -> list[str]:
    references: set[str] = set()
    for child in py_ast.walk(node):
        if isinstance(child, py_ast.Name) and isinstance(child.ctx, py_ast.Load):
            references.add(child.id)
        elif isinstance(child, py_ast.Attribute):
            references.add(child.attr)
        elif isinstance(child, py_ast.arg) and child.annotation is not None:
            reference = _python_expr_name(child.annotation)
            if reference:
                references.add(reference.rsplit(".", 1)[-1])
        elif isinstance(child, (py_ast.FunctionDef, py_ast.AsyncFunctionDef)) and child.returns is not None:
            reference = _python_expr_name(child.returns)
            if reference:
                references.add(reference.rsplit(".", 1)[-1])
        elif isinstance(child, py_ast.AnnAssign):
            reference = _python_expr_name(child.annotation)
            if reference:
                references.add(reference.rsplit(".", 1)[-1])
    return sorted(reference for reference in references if reference)


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


def _signature_line(lines: list[str], line_number: int) -> str | None:
    if line_number < 1 or line_number > len(lines):
        return None
    return lines[line_number - 1].strip().rstrip(":")
