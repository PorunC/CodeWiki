from backend.app.config import Settings
from backend.app.services.model_router import ModelRouter


def test_embedding_profile_uses_embedding_model() -> None:
    settings = Settings(
        llm_default_model="provider/default",
        llm_embedding_model="provider/embed",
    )
    profile = ModelRouter(settings).profile_for("embedding")

    assert profile.model == "provider/embed"


def test_qa_profile_streams_by_default() -> None:
    settings = Settings(llm_default_model="provider/default")
    profile = ModelRouter(settings).profile_for("qa")

    assert profile.model == "provider/default"
    assert profile.stream is True

