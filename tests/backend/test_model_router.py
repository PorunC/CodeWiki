from backend.app.config import LLMProfileSettings, LLMSettings, Settings
from backend.app.services.model_router import ModelRouter


def _test_settings(
    *,
    default: LLMProfileSettings | None = None,
    profiles: dict[str, LLMProfileSettings] | None = None,
) -> Settings:
    return Settings(
        _env_file=None,
        llm=LLMSettings(
            default=default or LLMProfileSettings(model="provider/strong-coding-model"),
            profiles=profiles or {},
        ),
    )


def test_default_profile_is_used_for_all_tasks_without_overrides() -> None:
    settings = _test_settings(
        default=LLMProfileSettings(
            model="provider/shared",
            provider_type="openai",
            endpoint="https://llm.example/v1",
            api_key="shared-key",
        ),
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
        profiles={"embedding": LLMProfileSettings(model="provider/embed")},
    )
    profile = ModelRouter(settings).profile_for("embedding")

    assert profile.model == "provider/embed"


def test_qa_profile_streams_by_default() -> None:
    settings = _test_settings(
        profiles={"qa": LLMProfileSettings(model="provider/qa")},
    )
    profile = ModelRouter(settings).profile_for("qa")

    assert profile.model == "provider/qa"
    assert profile.stream is True


def test_catalog_and_community_use_independent_task_models() -> None:
    settings = _test_settings(
        profiles={
            "catalog": LLMProfileSettings(model="provider/catalog"),
            "community_summary": LLMProfileSettings(model="provider/community"),
        },
    )
    router = ModelRouter(settings)

    assert router.profile_for("catalog").model == "provider/catalog"
    assert router.profile_for("community_summary").model == "provider/community"
    assert router.profile_for("cluster").model == "provider/community"


def test_page_qa_and_translation_can_use_explicit_task_models() -> None:
    settings = _test_settings(
        profiles={
            "page": LLMProfileSettings(model="provider/page"),
            "qa": LLMProfileSettings(model="provider/qa"),
            "translation": LLMProfileSettings(model="provider/translation"),
        },
    )
    router = ModelRouter(settings)

    assert router.profile_for("page").model == "provider/page"
    assert router.profile_for("qa").model == "provider/qa"
    assert router.profile_for("translation").model == "provider/translation"


def test_task_profile_carries_provider_endpoint_and_api_key() -> None:
    settings = _test_settings(
        default=LLMProfileSettings(
            model="provider/shared",
            provider_type="openai",
            endpoint="https://shared.example/v1",
            api_key="shared-key",
        ),
        profiles={
            "page": LLMProfileSettings(
                model="page-model",
                provider_type="anthropic",
                endpoint="https://llm.example/v1",
                api_key="task-key",
            )
        },
    )
    profile = ModelRouter(settings).profile_for("page")

    assert profile.model == "page-model"
    assert profile.provider_type == "anthropic"
    assert profile.endpoint == "https://llm.example/v1"
    assert profile.api_key == "task-key"


def test_task_profile_inherits_default_connection_when_only_model_is_overridden() -> None:
    settings = _test_settings(
        default=LLMProfileSettings(
            model="provider/shared",
            provider_type="openai",
            endpoint="https://shared.example/v1",
            api_key="shared-key",
        ),
        profiles={"catalog": LLMProfileSettings(model="provider/catalog")},
    )
    profile = ModelRouter(settings).profile_for("catalog")

    assert profile.model == "provider/catalog"
    assert profile.provider_type == "openai"
    assert profile.endpoint == "https://shared.example/v1"
    assert profile.api_key == "shared-key"
