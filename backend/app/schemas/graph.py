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
    reason: str | None = None
    is_inferred: bool = False
    provenance: dict[str, object] = Field(default_factory=dict)
    metadata: dict[str, object] = Field(default_factory=dict)


class GraphCommunity(BaseModel):
    id: str
    name: str
    level: int
    parent_id: str | None = None
    rank: int = 0
    node_ids: list[str]
    summary: str = ""


class GraphCommunityEdge(BaseModel):
    id: str
    source: str
    target: str
    type: str
    weight: float = 1.0
    confidence: float = 1.0
    reason: str | None = None
    evidence_edge_ids: list[str] = Field(default_factory=list)


class GraphResponse(BaseModel):
    repo_id: str
    nodes: list[CodeNode]
    edges: list[CodeEdge]
    communities: list[GraphCommunity] = Field(default_factory=list)
    community_edges: list[GraphCommunityEdge] = Field(default_factory=list)


class CodeNodeSearchHit(BaseModel):
    node: CodeNode
    score: float
    reasons: list[str] = Field(default_factory=list)


class GraphSearchResponse(BaseModel):
    repo_id: str
    query: str
    results: list[CodeNodeSearchHit]


class GraphRelationshipResponse(BaseModel):
    source: CodeNode
    target: CodeNode
    edge: CodeEdge


class GraphRelationshipsResponse(BaseModel):
    repo_id: str
    symbol: str
    relationships: list[GraphRelationshipResponse]


class GraphSubgraphResponse(BaseModel):
    repo_id: str
    root_ids: list[str]
    nodes: list[CodeNode]
    edges: list[CodeEdge]


class GraphExploreRequest(BaseModel):
    query: str
    max_files: int = 12
    max_nodes: int = 160


class GraphExploreResponse(BaseModel):
    repo_id: str
    query: str
    entry_points: list[dict[str, object]]
    relationships: list[dict[str, object]]
    source_sections: list[dict[str, object]]
    additional_files: list[dict[str, object]]
    text: str
    stats: dict[str, int]


class GraphAffectedRequest(BaseModel):
    file_paths: list[str]
    depth: int = 5
    test_glob: str | None = None


class GraphAffectedResponse(BaseModel):
    repo_id: str
    changed_files: list[str]
    affected_files: list[str]
    affected_tests: list[str]
    affected_wiki_pages: list[str]
    affected_node_ids: list[str]
    traversed_file_count: int


class GraphStatusResponse(BaseModel):
    repo_id: str
    file_count: int
    node_count: int
    edge_count: int
    nodes_by_type: dict[str, int]
    edges_by_type: dict[str, int]
    languages: dict[str, int]
