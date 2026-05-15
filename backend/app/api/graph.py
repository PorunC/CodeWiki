from dataclasses import asdict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.app.config import get_settings
from backend.app.database import get_store
from backend.app.schemas.graph import CodeEdge, CodeNode, GraphCommunity, GraphResponse
from backend.app.services.community_namer import CommunityNamer
from backend.app.services.graph_provenance import edge_provenance, node_confidence, node_provenance
from backend.app.services.graphrag import GraphRAGRetriever
from backend.app.services.llm_gateway import LLMGateway

router = APIRouter()


class BuildGraphRAGRequest(BaseModel):
    include_embeddings: bool = False


class RetrieveRequest(BaseModel):
    query: str
    max_hops: int = 2
    include_embeddings: bool = False


class NameCommunitiesRequest(BaseModel):
    max_communities: int = 40


@router.get("/{repo_id}/graph")
async def get_graph(repo_id: str) -> GraphResponse:
    store = get_store()
    if store.get_repo(repo_id) is None:
        raise HTTPException(status_code=404, detail=f"Repository not found: {repo_id}")
    nodes, edges = store.get_graph(repo_id)
    communities = store.list_graph_communities(repo_id)
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
                confidence=node_confidence(node.metadata),
                provenance=node_provenance(node.metadata),
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
                confidence_level=(
                    str(edge.metadata["confidence_level"])
                    if isinstance(edge.metadata.get("confidence_level"), str)
                    else None
                ),
                is_inferred=edge.is_inferred,
                provenance=edge_provenance(edge.metadata),
                metadata=edge.metadata,
            )
            for edge in edges
        ],
        communities=[
            GraphCommunity(
                id=community.id,
                name=community.name,
                level=community.level,
                node_ids=community.node_ids,
                summary=community.summary or "",
            )
            for community in communities
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
    return [
        {
            "id": community.id,
            "name": community.name,
            "level": str(community.level),
            "summary": community.summary or "",
        }
        for community in get_store().list_graph_communities(repo_id)
    ]


@router.post("/{repo_id}/communities/name")
async def name_communities(
    repo_id: str,
    payload: NameCommunitiesRequest | None = None,
) -> dict[str, object]:
    store = get_store()
    if store.get_repo(repo_id) is None:
        raise HTTPException(status_code=404, detail=f"Repository not found: {repo_id}")
    request = payload or NameCommunitiesRequest()
    try:
        result = await CommunityNamer(
            LLMGateway(get_settings()),
            store=store,
        ).summarize_communities(repo_id, max_communities=request.max_communities)
    except ValueError as exc:
        message = str(exc)
        status_code = 404 if message.startswith("Repository not found") else 400
        raise HTTPException(status_code=status_code, detail=message) from exc
    return asdict(result)


@router.post("/{repo_id}/graphrag/build")
async def build_graphrag(
    repo_id: str,
    payload: BuildGraphRAGRequest | None = None,
) -> dict[str, object]:
    request = payload or BuildGraphRAGRequest()
    store = get_store()
    settings = get_settings()
    try:
        result = await GraphRAGRetriever(store=store, settings=settings).build_index(
            repo_id,
            include_embeddings=request.include_embeddings,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return asdict(result)


@router.post("/{repo_id}/graphrag/retrieve")
async def retrieve_context(repo_id: str, payload: RetrieveRequest) -> dict[str, object]:
    store = get_store()
    settings = get_settings()
    try:
        trace = await GraphRAGRetriever(store=store, settings=settings).retrieve(
            repo_id,
            payload.query,
            max_hops=payload.max_hops,
            include_embeddings=payload.include_embeddings,
        )
    except ValueError as exc:
        message = str(exc)
        status_code = 404 if message.startswith("Repository not found") else 400
        raise HTTPException(status_code=status_code, detail=message) from exc
    return asdict(trace)


@router.get("/{repo_id}/graphrag/traces/{trace_id}")
async def get_retrieval_trace(repo_id: str, trace_id: str) -> dict[str, object]:
    return {"repo_id": repo_id, "trace_id": trace_id, "status": "not_persisted_yet"}
