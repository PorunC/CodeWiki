from fastapi import APIRouter
from pydantic import BaseModel

from backend.app.config import get_settings

router = APIRouter()


class TestModelRequest(BaseModel):
    model: str | None = None
    task_type: str = "qa"


@router.get("/llm/models")
async def get_llm_models() -> dict[str, str]:
    settings = get_settings()
    return {
        "mode": settings.llm_mode,
        "default_model": settings.llm_default_model,
        "embedding_model": settings.llm_embedding_model,
    }


@router.post("/llm/test")
async def test_llm_model(payload: TestModelRequest) -> dict[str, str]:
    return {"status": "not_implemented", "task_type": payload.task_type, "model": payload.model or ""}
