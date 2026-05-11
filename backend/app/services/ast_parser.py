import ast as py_ast
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from backend.app.services.language_detector import LanguageDetector


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
    calls: list[str] = field(default_factory=list)
    hash: str = ""


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
        registry.register(JavaScriptLikeParser("javascript"))
        registry.register(JavaScriptLikeParser("jsx"))
        registry.register(JavaScriptLikeParser("typescript"))
        registry.register(JavaScriptLikeParser("tsx"))
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
        self.symbols.append(
            AstSymbol(
                id=symbol_id,
                type="class",
                name=node.name,
                file_path=self.file_path,
                language="python",
                start_line=node.lineno,
                end_line=getattr(node, "end_lineno", node.lineno),
                parent_id=parent_id,
                docstring=py_ast.get_docstring(node),
                calls=_python_calls(node),
                hash=self.file_hash,
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
                calls=_python_calls(node),
                hash=self.file_hash,
            )
        )


class JavaScriptLikeParser:
    _import_from_pattern = re.compile(r"^\s*import\s+(?:.+?\s+from\s+)?[\"']([^\"']+)[\"']")
    _require_pattern = re.compile(r"\brequire\(\s*[\"']([^\"']+)[\"']\s*\)")
    _class_pattern = re.compile(r"^\s*(?:export\s+)?(?:default\s+)?class\s+([A-Za-z_$][\w$]*)")
    _function_pattern = re.compile(
        r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)"
    )
    _arrow_pattern = re.compile(
        r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s+)?"
        r"(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>"
    )
    _call_pattern = re.compile(r"\b([A-Za-z_$][\w$]*)\s*\(")
    _call_exclusions = {
        "if",
        "for",
        "while",
        "switch",
        "catch",
        "function",
        "return",
        "typeof",
        "import",
        "require",
    }

    def __init__(self, language: str) -> None:
        self.language = language

    def parse(self, path: Path, *, repo_root: Path | None = None) -> list[AstSymbol]:
        content = path.read_text(encoding="utf-8", errors="replace")
        file_path = _relative_path(path, repo_root)
        file_hash = _content_hash(content)
        lines = content.splitlines()
        imports = self._imports(lines)
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
                calls=self._calls(content),
                hash=file_hash,
            )
        ]

        for index, line in enumerate(lines, start=1):
            class_match = self._class_pattern.match(line)
            if class_match:
                name = class_match.group(1)
                symbols.append(
                    AstSymbol(
                        id=f"{file_path}::{name}",
                        type="class",
                        name=name,
                        file_path=file_path,
                        language=self.language,
                        start_line=index,
                        end_line=index,
                        signature=line.strip(),
                        hash=file_hash,
                    )
                )
                continue

            function_match = self._function_pattern.match(line) or self._arrow_pattern.match(line)
            if function_match:
                name = function_match.group(1)
                symbols.append(
                    AstSymbol(
                        id=f"{file_path}::{name}",
                        type="function",
                        name=name,
                        file_path=file_path,
                        language=self.language,
                        start_line=index,
                        end_line=index,
                        signature=line.strip(),
                        calls=self._calls(line),
                        hash=file_hash,
                    )
                )

        return symbols

    def _imports(self, lines: list[str]) -> list[str]:
        imports: list[str] = []
        for line in lines:
            import_match = self._import_from_pattern.match(line)
            if import_match:
                imports.append(import_match.group(1))
            imports.extend(self._require_pattern.findall(line))
        return sorted(set(imports))

    def _calls(self, content: str) -> list[str]:
        calls = {
            match.group(1)
            for match in self._call_pattern.finditer(content)
            if match.group(1) not in self._call_exclusions
        }
        return sorted(calls)


def _python_imports(tree: py_ast.AST) -> list[str]:
    imports: list[str] = []
    for node in py_ast.walk(tree):
        if isinstance(node, py_ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, py_ast.ImportFrom):
            module = "." * node.level + (node.module or "")
            imports.extend(f"{module}.{alias.name}".strip(".") for alias in node.names)
    return sorted(set(imports))


def _python_calls(node: py_ast.AST) -> list[str]:
    calls: set[str] = set()
    for child in py_ast.walk(node):
        if isinstance(child, py_ast.Call):
            if isinstance(child.func, py_ast.Name):
                calls.add(child.func.id)
            elif isinstance(child.func, py_ast.Attribute):
                calls.add(child.func.attr)
    return sorted(calls)


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
