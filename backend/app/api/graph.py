from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.app.database import get_store
from backend.app.schemas.graph import CodeEdge, CodeNode, GraphResponse

router = APIRouter()


class RetrieveRequest(BaseModel):
    query: str
    max_hops: int = 2


@router.get("/{repo_id}/graph")
async def get_graph(repo_id: str) -> GraphResponse:
    store = get_store()
    if store.get_repo(repo_id) is None:
        raise HTTPException(status_code=404, detail=f"Repository not found: {repo_id}")
    nodes, edges = store.get_graph(repo_id)
    return GraphResponse(
        repo_id=repo_id,
        nodes=[
            CodeNode(
                id=node.id,
                type=node.type,
                name=node.name,
                file_path=node.file_path,
                start_line=node.start_line,
                end_line=node.end_line,
                language=node.language,
                symbol_id=node.symbol_id,
                metadata=node.metadata,
            )
            for node in nodes
        ],
        edges=[
            CodeEdge(
                id=edge.id,
                source=edge.source_id,
                target=edge.target_id,
                type=edge.type,
                confidence=edge.confidence,
                is_inferred=edge.is_inferred,
                metadata=edge.metadata,
            )
            for edge in edges
        ],
    )


@router.get("/{repo_id}/graph/nodes/{node_id}")
async def get_node(repo_id: str, node_id: str) -> dict[str, str]:
    nodes, edges = get_store().get_graph(repo_id)
    node = next((item for item in nodes if item.id == node_id), None)
    if node is None:
        raise HTTPException(status_code=404, detail=f"Node not found: {node_id}")
    adjacent_edges = [
        edge for edge in edges if edge.source_id == node_id or edge.target_id == node_id
    ]
    return {
        "repo_id": repo_id,
        "node_id": node_id,
        "type": node.type,
        "name": node.name,
        "file_path": node.file_path,
        "adjacent_edge_count": str(len(adjacent_edges)),
    }


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
