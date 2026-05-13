from dataclasses import dataclass, field


@dataclass(frozen=True)
class CodeGraphNode:
    id: str
    repo_id: str
    type: str
    name: str
    file_path: str = ""
    start_line: int | None = None
    end_line: int | None = None
    language: str | None = None
    symbol_id: str | None = None
    summary: str | None = None
    hash: str = ""
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class CodeGraphEdge:
    id: str
    repo_id: str
    source_id: str
    target_id: str
    type: str
    confidence: float = 1.0
    weight: float = 1.0
    is_inferred: bool = False
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class CodeGraph:
    repo_id: str
    nodes: list[CodeGraphNode]
    edges: list[CodeGraphEdge]
