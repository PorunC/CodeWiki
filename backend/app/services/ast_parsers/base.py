from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


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
    implements: list[str] = field(default_factory=list)
    decorators: list[str] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)
    references: list[str] = field(default_factory=list)
    hash: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class LanguageParser(Protocol):
    language: str

    def parse(self, path: Path, *, repo_root: Path | None = None) -> list[AstSymbol]:
        ...
