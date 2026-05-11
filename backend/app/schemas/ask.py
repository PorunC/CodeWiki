from pydantic import BaseModel, Field


class SourceRef(BaseModel):
    file_path: str
    start_line: int
    end_line: int


class AskRequest(BaseModel):
    question: str = Field(min_length=1)
    mode: str = "graph_rag"
    max_hops: int = 2
    include_sources: bool = True
    include_graph: bool = True


class AskResponse(BaseModel):
    answer: str
    sources: list[SourceRef]
    related_nodes: list[dict[str, object]]
    related_edges: list[dict[str, object]]
    trace_id: str

