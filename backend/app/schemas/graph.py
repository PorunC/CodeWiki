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
    confidence: float = 1.0
    provenance: dict[str, object] = Field(default_factory=dict)
    metadata: dict[str, object] = Field(default_factory=dict)


class CodeEdge(BaseModel):
    id: str
    source: str
    target: str
    type: str
    confidence: float = 1.0
    confidence_level: str | None = None
    is_inferred: bool = False
    provenance: dict[str, object] = Field(default_factory=dict)
    metadata: dict[str, object] = Field(default_factory=dict)


class GraphCommunity(BaseModel):
    id: str
    name: str
    level: int
    node_ids: list[str]
    summary: str = ""


class GraphResponse(BaseModel):
    repo_id: str
    nodes: list[CodeNode]
    edges: list[CodeEdge]
    communities: list[GraphCommunity] = Field(default_factory=list)
