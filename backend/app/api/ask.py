from fastapi import APIRouter

from backend.app.schemas.ask import AskRequest, AskResponse

router = APIRouter()


@router.post("/{repo_id}/ask")
async def ask_repo(repo_id: str, payload: AskRequest) -> AskResponse:
    return AskResponse(
        answer="GraphRAG is not built yet. Run analysis and retrieval indexing first.",
        sources=[],
        related_nodes=[],
        related_edges=[],
        trace_id=f"{repo_id}:{hash(payload.question)}",
    )

