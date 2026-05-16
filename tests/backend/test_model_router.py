from backend.app.config import Settings
from backend.app.services.model_router import ModelRouter


def _test_settings(**overrides) -> Settings:
    defaults = {
        "llm_provider": None,
        "llm_endpoint": None,
        "llm_api_key": None,
        "llm_catalog_model": None,
        "llm_catalog_provider": None,
        "llm_catalog_endpoint": None,
        "llm_catalog_api_key": None,
        "llm_community_model": None,
        "llm_community_provider": None,
        "llm_community_endpoint": None,
        "llm_community_api_key": None,
        "llm_page_model": None,
        "llm_page_provider": None,
        "llm_page_endpoint": None,
        "llm_page_api_key": None,
        "llm_translation_model": None,
        "llm_translation_provider": None,
        "llm_translation_endpoint": None,
        "llm_translation_api_key": None,
        "llm_qa_model": None,
        "llm_qa_provider": None,
        "llm_qa_endpoint": None,
        "llm_qa_api_key": None,
        "llm_embedding_model": None,
        "llm_embedding_provider": None,
        "llm_embedding_endpoint": None,
        "llm_embedding_api_key": None,
    }
    return Settings(_env_file=None, **(defaults | overrides))


def test_default_profile_is_used_for_all_tasks_without_overrides() -> None:
    settings = _test_settings(
        llm_model="provider/shared",
        llm_provider="openai",
        llm_endpoint="https://llm.example/v1",
        llm_api_key="shared-key",
    )
    router = ModelRouter(settings)

    for task_type in ("catalog", "community_summary", "page", "translation", "qa", "embedding"):
        profile = router.profile_for(task_type)
        assert profile.model == "provider/shared"
        assert profile.provider_type == "openai"
        assert profile.endpoint == "https://llm.example/v1"
        assert profile.api_key == "shared-key"


def test_embedding_profile_uses_embedding_model() -> None:
    settings = _test_settings(
        llm_embedding_model="provider/embed",
    )
    profile = ModelRouter(settings).profile_for("embedding")

    assert profile.model == "provider/embed"


def test_qa_profile_streams_by_default() -> None:
    settings = _test_settings(
        llm_qa_model="provider/qa",
    )
    profile = ModelRouter(settings).profile_for("qa")

    assert profile.model == "provider/qa"
    assert profile.stream is True


def test_catalog_and_community_use_independent_task_models() -> None:
    settings = _test_settings(
        llm_catalog_model="provider/catalog",
        llm_community_model="provider/community",
    )
    router = ModelRouter(settings)

    assert router.profile_for("catalog").model == "provider/catalog"
    assert router.profile_for("community_summary").model == "provider/community"


def test_page_qa_and_translation_can_use_explicit_task_models() -> None:
    settings = _test_settings(
        llm_page_model="provider/page",
        llm_qa_model="provider/qa",
        llm_translation_model="provider/translation",
    )
    router = ModelRouter(settings)

    assert router.profile_for("page").model == "provider/page"
    assert router.profile_for("qa").model == "provider/qa"
    assert router.profile_for("translation").model == "provider/translation"


def test_task_profile_carries_provider_endpoint_and_api_key() -> None:
    settings = _test_settings(
        llm_model="provider/shared",
        llm_provider="openai",
        llm_endpoint="https://shared.example/v1",
        llm_api_key="shared-key",
        llm_page_model="page-model",
        llm_page_provider="anthropic",
        llm_page_endpoint="https://llm.example/v1",
        llm_page_api_key="task-key",
    )
    profile = ModelRouter(settings).profile_for("page")

    assert profile.model == "page-model"
    assert profile.provider_type == "anthropic"
    assert profile.endpoint == "https://llm.example/v1"
    assert profile.api_key == "task-key"


def test_task_profile_inherits_default_connection_when_only_model_is_overridden() -> None:
    settings = _test_settings(
        llm_model="provider/shared",
        llm_provider="openai",
        llm_endpoint="https://shared.example/v1",
        llm_api_key="shared-key",
        llm_catalog_model="provider/catalog",
    )
    profile = ModelRouter(settings).profile_for("catalog")

    assert profile.model == "provider/catalog"
    assert profile.provider_type == "openai"
    assert profile.endpoint == "https://shared.example/v1"
    assert profile.api_key == "shared-key"
