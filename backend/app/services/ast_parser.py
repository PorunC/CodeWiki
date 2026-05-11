from dataclasses import dataclass, field
from pathlib import Path


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


class AstParser:
    """Parser registry facade.

    The first real milestone will register language-specific tree-sitter extractors here.
    """

    def parse_file(self, path: Path) -> list[AstSymbol]:
        raise NotImplementedError(f"No parser registered for {path.suffix}")

