from fastapi import APIRouter
from pydantic import BaseModel

from backend.app.config import get_settings
from backend.app.services.llm.model_router import ModelRouter

router = APIRouter()


class TestModelRequest(BaseModel):
    model: str | None = None
    task_type: str = "qa"


@router.get("/llm/models")
async def get_llm_models() -> dict[str, object]:
    settings = get_settings()
    model_router = ModelRouter(settings)
    profiles = {
        task_type: _profile_payload(model_router.profile_for(task_type))
        for task_type in (
            "catalog",
            "community_summary",
            "cluster",
            "page",
            "translation",
            "qa",
            "embedding",
        )
    }
    return {
        "mode": settings.llm.mode,
        "default_profile": _profile_payload(model_router.default_profile()),
        "profiles": profiles,
    }


@router.post("/llm/test")
async def test_llm_model(payload: TestModelRequest) -> dict[str, str]:
    return {"status": "not_implemented", "task_type": payload.task_type, "model": payload.model or ""}


def _profile_payload(profile) -> dict[str, object]:
    return {
        "model": profile.model,
        "provider_type": profile.provider_type or "",
        "endpoint": profile.endpoint or "",
        "has_api_key": bool(profile.api_key),
        "stream": profile.stream,
        "max_tokens": profile.max_tokens,
    }
