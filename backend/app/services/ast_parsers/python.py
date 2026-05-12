import ast as py_ast
from pathlib import Path

from backend.app.services.ast_parsers.base import AstSymbol
from backend.app.services.ast_parsers.common import HTTP_METHODS, content_hash, relative_path


class PythonAstParser:
    language = "python"

    def parse(self, path: Path, *, repo_root: Path | None = None) -> list[AstSymbol]:
        content = path.read_text(encoding="utf-8", errors="replace")
        file_path = relative_path(path, repo_root)
        file_hash = content_hash(content)
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


def _signature_line(lines: list[str], line_number: int) -> str | None:
    if line_number < 1 or line_number > len(lines):
        return None
    return lines[line_number - 1].strip().rstrip(":")
