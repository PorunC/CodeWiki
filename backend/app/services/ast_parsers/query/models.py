from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


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
class DefinitionRecord:
    kind: str
    node: Any
    name: str
    parent_name: str = ""
    bases: set[str] = field(default_factory=set)
    implements: set[str] = field(default_factory=set)
    calls: set[str] = field(default_factory=set)
    references: set[str] = field(default_factory=set)
    exported: bool = False
