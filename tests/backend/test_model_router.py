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


def test_task_default_max_tokens_are_used_without_overrides() -> None:
    router = ModelRouter(_test_settings())

    assert router.profile_for("catalog").max_tokens == 4096
    assert router.profile_for("community_summary").max_tokens == 4096
    assert router.profile_for("cluster").max_tokens == 4096
    assert router.profile_for("page").max_tokens == 12000
    assert router.profile_for("translation").max_tokens == 12000
    assert router.profile_for("qa").max_tokens is None
    assert router.profile_for("embedding").max_tokens is None


def test_task_profile_can_override_max_tokens() -> None:
    settings = _test_settings(
        profiles={
            "catalog": LLMProfileSettings(model="provider/catalog", max_tokens=10000),
            "page": LLMProfileSettings(model="provider/page", max_tokens=16000),
        },
    )
    router = ModelRouter(settings)

    assert router.profile_for("catalog").max_tokens == 10000
    assert router.profile_for("page").max_tokens == 16000


def test_default_profile_max_tokens_overrides_task_defaults() -> None:
    settings = _test_settings(
        default=LLMProfileSettings(model="provider/shared", max_tokens=9000),
    )
    router = ModelRouter(settings)

    assert router.profile_for("catalog").max_tokens == 9000
    assert router.profile_for("page").max_tokens == 9000
    assert router.profile_for("qa").max_tokens == 9000


def test_zero_max_tokens_disables_provider_limit() -> None:
    settings = _test_settings(
        profiles={"catalog": LLMProfileSettings(model="provider/catalog", max_tokens=0)},
    )

    assert ModelRouter(settings).profile_for("catalog").max_tokens is None


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


def test_cluster_profile_overrides_community_alias_when_configured() -> None:
    settings = _test_settings(
        profiles={
            "community_summary": LLMProfileSettings(model="provider/community", max_tokens=4096),
            "cluster": LLMProfileSettings(model="provider/cluster", max_tokens=8192),
        },
    )
    profile = ModelRouter(settings).profile_for("cluster")

    assert profile.model == "provider/cluster"
    assert profile.max_tokens == 8192


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


def test_profile_max_tokens_loads_from_nested_env_file(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "CODEWIKI_LLM__DEFAULT__MODEL=provider/shared",
                "CODEWIKI_LLM__PROFILES__CATALOG__MAX_TOKENS=11000",
                "CODEWIKI_LLM__PROFILES__PAGE__MAX_TOKENS=",
            ]
        ),
        encoding="utf-8",
    )
    router = ModelRouter(Settings(_env_file=env_file))

    assert router.profile_for("catalog").max_tokens == 11000
    assert router.profile_for("page").max_tokens == 12000
