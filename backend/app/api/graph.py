from fastapi import APIRouter
from pydantic import BaseModel

from backend.app.schemas.graph import GraphResponse

router = APIRouter()


class RetrieveRequest(BaseModel):
    query: str
    max_hops: int = 2


@router.get("/{repo_id}/graph")
async def get_graph(repo_id: str) -> GraphResponse:
    return GraphResponse(repo_id=repo_id, nodes=[], edges=[])


@router.get("/{repo_id}/graph/nodes/{node_id}")
async def get_node(repo_id: str, node_id: str) -> dict[str, str]:
    return {"repo_id": repo_id, "node_id": node_id}


@router.get("/{repo_id}/communities")
async def get_communities(repo_id: str) -> list[dict[str, str]]:
    return []


@router.post("/{repo_id}/graphrag/build")
async def build_graphrag(repo_id: str) -> dict[str, str]:
    return {"repo_id": repo_id, "status": "queued"}


@router.post("/{repo_id}/graphrag/retrieve")
async def retrieve_context(repo_id: str, payload: RetrieveRequest) -> dict[str, object]:
    return {
        "repo_id": repo_id,
        "query": payload.query,
        "max_hops": payload.max_hops,
        "seed_nodes": [],
        "expanded_nodes": [],
        "source_chunks": [],
        "trace_id": f"{repo_id}:{hash(payload.query)}",
    }


@router.get("/{repo_id}/graphrag/traces/{trace_id}")
async def get_retrieval_trace(repo_id: str, trace_id: str) -> dict[str, object]:
    return {"repo_id": repo_id, "trace_id": trace_id, "status": "not_persisted_yet"}
