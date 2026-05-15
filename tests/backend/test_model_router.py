from backend.app.config import Settings
from backend.app.services.model_router import ModelRouter


def _test_settings(**overrides) -> Settings:
    defaults = {
        "llm_catalog_model": None,
        "llm_community_model": None,
        "llm_page_model": None,
        "llm_qa_model": None,
    }
    return Settings(_env_file=None, **(defaults | overrides))


def test_embedding_profile_uses_embedding_model() -> None:
    settings = _test_settings(
        llm_default_model="provider/default",
        llm_embedding_model="provider/embed",
    )
    profile = ModelRouter(settings).profile_for("embedding")

    assert profile.model == "provider/embed"


def test_qa_profile_streams_by_default() -> None:
    settings = _test_settings(
        llm_default_model="provider/default",
        llm_large_model="provider/large",
    )
    profile = ModelRouter(settings).profile_for("qa")

    assert profile.model == "provider/large"
    assert profile.stream is True


def test_catalog_and_community_use_small_model() -> None:
    settings = _test_settings(
        llm_default_model="provider/default",
        llm_small_model="provider/small",
    )
    router = ModelRouter(settings)

    assert router.profile_for("catalog").model == "provider/small"
    assert router.profile_for("community_summary").model == "provider/small"


def test_page_and_qa_can_use_explicit_task_models() -> None:
    settings = _test_settings(
        llm_default_model="provider/default",
        llm_large_model="provider/large",
        llm_page_model="provider/page",
        llm_qa_model="provider/qa",
    )
    router = ModelRouter(settings)

    assert router.profile_for("page").model == "provider/page"
    assert router.profile_for("qa").model == "provider/qa"
