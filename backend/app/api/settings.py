from fastapi import APIRouter
from pydantic import BaseModel

from backend.app.config import get_settings
from backend.app.services.model_router import ModelRouter

router = APIRouter()


class TestModelRequest(BaseModel):
    model: str | None = None
    task_type: str = "qa"


@router.get("/llm/models")
async def get_llm_models() -> dict[str, str]:
    settings = get_settings()
    router = ModelRouter(settings)
    return {
        "mode": settings.llm_mode,
        "base_url": settings.llm_base_url or settings.litellm_proxy_base_url or "",
        "default_model": settings.llm_default_model,
        "small_model": settings.llm_small_model or settings.llm_default_model,
        "large_model": settings.llm_large_model or settings.llm_default_model,
        "catalog_model": router.profile_for("catalog").model,
        "community_model": router.profile_for("community_summary").model,
        "page_model": router.profile_for("page").model,
        "qa_model": router.profile_for("qa").model,
        "embedding_model": settings.llm_embedding_model,
    }


@router.post("/llm/test")
async def test_llm_model(payload: TestModelRequest) -> dict[str, str]:
    return {"status": "not_implemented", "task_type": payload.task_type, "model": payload.model or ""}
