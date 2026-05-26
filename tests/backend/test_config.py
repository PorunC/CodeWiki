from backend.app.config import Settings


def test_graphrag_settings_load_from_env_file(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "CODEWIKI_GRAPHRAG_CONTEXT_TOKEN_BUDGET=16000",
                "CODEWIKI_GRAPHRAG_MAX_SOURCE_CHUNKS=40",
            ]
        ),
        encoding="utf-8",
    )

    settings = Settings(_env_file=env_file)

    assert settings.graphrag_context_token_budget == 16000
    assert settings.graphrag_max_source_chunks == 40
