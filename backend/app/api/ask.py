from fastapi import APIRouter, HTTPException

from backend.app.config import get_settings
from backend.app.database import get_store
from backend.app.schemas.ask import AskRequest, AskResponse
from backend.app.services.graphrag import GraphRAGRetriever
from backend.app.services.llm.gateway import LLMGateway
from backend.app.services.llm.run_recorder import LLMCallError
from backend.app.services.question_answerer import QuestionAnswerer

router = APIRouter()


@router.post("/{repo_id}/ask")
async def ask_repo(repo_id: str, payload: AskRequest) -> AskResponse:
    settings = get_settings()
    store = get_store()
    answerer = QuestionAnswerer(
        GraphRAGRetriever(store=store, settings=settings),
        LLMGateway(settings),
        store=store,
    )
    try:
        return await answerer.answer(repo_id, payload)
    except LLMCallError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "message": str(exc),
                "task_type": exc.task_type,
                "run_id": exc.run_id,
            },
        ) from exc
    except ValueError as exc:
        message = str(exc)
        status_code = 404 if message.startswith("Repository not found") else 400
        raise HTTPException(status_code=status_code, detail=message) from exc
