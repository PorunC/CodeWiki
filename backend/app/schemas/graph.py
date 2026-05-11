from pydantic import BaseModel, Field


class CodeNode(BaseModel):
    id: str
    type: str
    name: str
    file_path: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    language: str | None = None
    symbol_id: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class CodeEdge(BaseModel):
    id: str
    source: str
    target: str
    type: str
    confidence: float = 1.0
    is_inferred: bool = False
    metadata: dict[str, object] = Field(default_factory=dict)


class GraphResponse(BaseModel):
    repo_id: str
    nodes: list[CodeNode]
    edges: list[CodeEdge]
