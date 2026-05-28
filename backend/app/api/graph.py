from dataclasses import asdict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.app.config import get_settings
from backend.app.database import get_store
from backend.app.schemas.graph import (
    CodeEdge,
    CodeNode,
    CodeNodeSearchHit,
    GraphAffectedRequest,
    GraphAffectedResponse,
    GraphCommunity,
    GraphCommunityEdge,
    GraphExploreRequest,
    GraphExploreResponse,
    GraphRelationshipResponse,
    GraphRelationshipsResponse,
    GraphResponse,
    GraphSearchResponse,
    GraphStatusResponse,
    GraphSubgraphResponse,
)
from backend.app.services.async_tasks import repo_write_lock, run_blocking
from backend.app.services.community.namer import CommunityNamer
from backend.app.services.graph_provenance import edge_provenance, node_confidence, node_provenance
from backend.app.services.graph.query import GraphQueryService
from backend.app.services.graphrag import GraphRAGRetriever
from backend.app.services.llm.gateway import LLMGateway

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
    try:
        return await run_blocking(_graph_response, repo_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _graph_response(repo_id: str) -> GraphResponse:
    store = get_store()
    if store.get_repo(repo_id) is None:
        raise ValueError(f"Repository not found: {repo_id}")
    nodes, edges = store.get_graph(repo_id)
    communities = store.list_graph_communities(repo_id)
    community_edges = store.list_graph_community_edges(repo_id)
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
                reason=(
                    str(edge.metadata["reason"])
                    if isinstance(edge.metadata.get("reason"), str)
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
                parent_id=community.parent_id,
                rank=community.rank,
                node_ids=community.node_ids,
                summary=community.summary or "",
            )
            for community in communities
        ],
        community_edges=[
            GraphCommunityEdge(
                id=edge.id,
                source=edge.source_community_id,
                target=edge.target_community_id,
                type=edge.type,
                weight=edge.weight,
                confidence=edge.confidence,
                reason=edge.reason,
                evidence_edge_ids=edge.evidence_edge_ids,
            )
            for edge in community_edges
        ],
    )


@router.get("/{repo_id}/graph/search")
async def search_graph(
    repo_id: str,
    q: str = "",
    type: str | None = None,
    language: str | None = None,
    path: str | None = None,
    name: str | None = None,
    limit: int = 20,
) -> GraphSearchResponse:
    store = get_store()
    try:
        hits = GraphQueryService(store=store).search(
            repo_id,
            q,
            types=[type] if type else None,
            languages=[language] if language else None,
            path_filters=[path] if path else None,
            name_filters=[name] if name else None,
            limit=limit,
        )
    except ValueError as exc:
        raise _graph_http_error(exc) from exc
    return GraphSearchResponse(
        repo_id=repo_id,
        query=q,
        results=[
            CodeNodeSearchHit(
                node=_node_response(hit.node),
                score=hit.score,
                reasons=list(hit.reasons),
            )
            for hit in hits
        ],
    )


@router.get("/{repo_id}/graph/callers")
async def graph_callers(repo_id: str, symbol: str, limit: int = 20) -> GraphRelationshipsResponse:
    store = get_store()
    try:
        relationships = GraphQueryService(store=store).callers(repo_id, symbol, limit=limit)
    except ValueError as exc:
        raise _graph_http_error(exc) from exc
    return GraphRelationshipsResponse(
        repo_id=repo_id,
        symbol=symbol,
        relationships=[
            GraphRelationshipResponse(
                source=_node_response(item.source),
                target=_node_response(item.target),
                edge=_edge_response(item.edge),
            )
            for item in relationships
        ],
    )


@router.get("/{repo_id}/graph/callees")
async def graph_callees(repo_id: str, symbol: str, limit: int = 20) -> GraphRelationshipsResponse:
    store = get_store()
    try:
        relationships = GraphQueryService(store=store).callees(repo_id, symbol, limit=limit)
    except ValueError as exc:
        raise _graph_http_error(exc) from exc
    return GraphRelationshipsResponse(
        repo_id=repo_id,
        symbol=symbol,
        relationships=[
            GraphRelationshipResponse(
                source=_node_response(item.source),
                target=_node_response(item.target),
                edge=_edge_response(item.edge),
            )
            for item in relationships
        ],
    )


@router.get("/{repo_id}/graph/impact")
async def graph_impact(repo_id: str, symbol: str, depth: int = 2) -> GraphSubgraphResponse:
    store = get_store()
    try:
        result = GraphQueryService(store=store).impact(repo_id, symbol, depth=depth)
    except ValueError as exc:
        raise _graph_http_error(exc) from exc
    return GraphSubgraphResponse(
        repo_id=repo_id,
        root_ids=result.root_ids,
        nodes=[_node_response(node) for node in result.nodes],
        edges=[_edge_response(edge) for edge in result.edges],
    )


@router.post("/{repo_id}/graph/explore")
async def graph_explore(repo_id: str, payload: GraphExploreRequest) -> GraphExploreResponse:
    store = get_store()
    try:
        result = GraphQueryService(store=store).explore(
            repo_id,
            payload.query,
            max_files=payload.max_files,
            max_nodes=payload.max_nodes,
        )
    except ValueError as exc:
        raise _graph_http_error(exc) from exc
    return GraphExploreResponse(
        repo_id=result.repo_id,
        query=result.query,
        entry_points=result.entry_points,
        relationships=result.relationships,
        source_sections=[asdict(section) for section in result.source_sections],
        additional_files=result.additional_files,
        text=result.text,
        stats=result.stats,
    )


@router.post("/{repo_id}/graph/affected")
async def graph_affected(repo_id: str, payload: GraphAffectedRequest) -> GraphAffectedResponse:
    store = get_store()
    try:
        result = GraphQueryService(store=store).affected(
            repo_id,
            payload.file_paths,
            depth=payload.depth,
            test_glob=payload.test_glob,
        )
    except ValueError as exc:
        raise _graph_http_error(exc) from exc
    return GraphAffectedResponse(**asdict(result))


@router.get("/{repo_id}/graph/status")
async def graph_status(repo_id: str) -> GraphStatusResponse:
    try:
        return await run_blocking(_graph_status_response, repo_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _graph_status_response(repo_id: str) -> GraphStatusResponse:
    store = get_store()
    if store.get_repo(repo_id) is None:
        raise ValueError(f"Repository not found: {repo_id}")
    nodes, edges = store.get_graph(repo_id)
    nodes_by_type: dict[str, int] = {}
    edges_by_type: dict[str, int] = {}
    languages: dict[str, int] = {}
    for node in nodes:
        nodes_by_type[node.type] = nodes_by_type.get(node.type, 0) + 1
        if node.language:
            languages[node.language] = languages.get(node.language, 0) + 1
    for edge in edges:
        edges_by_type[edge.type] = edges_by_type.get(edge.type, 0) + 1
    return GraphStatusResponse(
        repo_id=repo_id,
        file_count=sum(1 for node in nodes if node.type in {"file", "config"}),
        node_count=len(nodes),
        edge_count=len(edges),
        chunk_count=len(store.list_code_chunks(repo_id)),
        nodes_by_type=nodes_by_type,
        edges_by_type=edges_by_type,
        languages=languages,
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
async def get_communities(repo_id: str) -> list[dict[str, object]]:
    return [
        {
            "id": community.id,
            "name": community.name,
            "level": community.level,
            "parent_id": community.parent_id,
            "rank": community.rank,
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
        async with repo_write_lock(repo_id):
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
        async with repo_write_lock(repo_id):
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


def _node_response(node) -> CodeNode:
    return CodeNode(
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


def _edge_response(edge) -> CodeEdge:
    return CodeEdge(
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
        reason=(
            str(edge.metadata["reason"])
            if isinstance(edge.metadata.get("reason"), str)
            else None
        ),
        is_inferred=edge.is_inferred,
        provenance=edge_provenance(edge.metadata),
        metadata=edge.metadata,
    )


def _graph_http_error(exc: ValueError) -> HTTPException:
    message = str(exc)
    status_code = 404 if message.startswith("Repository not found") else 400
    return HTTPException(status_code=status_code, detail=message)
