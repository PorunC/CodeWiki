from pathlib import Path

import click

from backend.app.config import get_settings
from backend.app.database import get_store
from backend.app.cli.common import echo_json, echo_table
from backend.app.env_config import (
    LLM_PROFILES,
    codewiki_values,
    ensure_env_file,
    llm_profile_key,
    mask_config_values,
    parse_env_assignment,
    read_env_values,
    validate_env_key,
    write_env_values,
)


def register(main: click.Group) -> None:
    @main.command("config")
    @click.option(
        "--env-file",
        type=click.Path(dir_okay=False, path_type=Path),
        default=Path(".env"),
        show_default=True,
        help="Environment file to read or update.",
    )
    @click.option("--init", "initialize", is_flag=True, help="Create the env file from .env.example.")
    @click.option("--path", "show_path", is_flag=True, help="Print the resolved env file path.")
    @click.option("--list", "list_values", is_flag=True, help="List configured CODEWIKI_* values.")
    @click.option("--get", "get_keys", multiple=True, metavar="KEY", help="Print one env variable.")
    @click.option("--set", "assignment_values", multiple=True, metavar="KEY=VALUE", help="Set an env variable.")
    @click.option(
        "--profile",
        type=click.Choice(LLM_PROFILES),
        default="default",
        show_default=True,
        help="LLM profile used by --model, --provider-type, --endpoint, --api-key, and --max-tokens.",
    )
    @click.option("--model", help="Set the selected LLM profile model.")
    @click.option("--provider-type", help="Set the selected LLM profile provider type.")
    @click.option("--endpoint", help="Set the selected LLM profile endpoint.")
    @click.option("--api-key", help="Set the selected LLM profile API key.")
    @click.option(
        "--max-tokens",
        type=click.IntRange(min=0),
        help="Set the selected LLM profile max output tokens. Use 0 to omit provider max_tokens.",
    )
    @click.option("--base-language", help="Set CODEWIKI_WIKI_BASE_LANGUAGE.")
    @click.option("--translation-languages", help="Set CODEWIKI_WIKI_TRANSLATION_LANGUAGES.")
    @click.option("--show-secrets", is_flag=True, help="Do not mask secret values in command output.")
    @click.option("--json", "as_json", is_flag=True, help="Print JSON output.")
    def configure_env(
        env_file: Path,
        initialize: bool,
        show_path: bool,
        list_values: bool,
        get_keys: tuple[str, ...],
        assignment_values: tuple[str, ...],
        profile: str,
        model: str | None,
        provider_type: str | None,
        endpoint: str | None,
        api_key: str | None,
        max_tokens: int | None,
        base_language: str | None,
        translation_languages: str | None,
        show_secrets: bool,
        as_json: bool,
    ) -> None:
        """Configure CodeWiki environment variables in an env file."""
        env_file = env_file.expanduser().resolve()
        example_file = Path(__file__).resolve().parents[3] / ".env.example"
        updates = _config_updates(
            assignment_values=assignment_values,
            profile=profile,
            model=model,
            provider_type=provider_type,
            endpoint=endpoint,
            api_key=api_key,
            max_tokens=max_tokens,
            base_language=base_language,
            translation_languages=translation_languages,
        )
        has_read_action = show_path or list_values or bool(get_keys)
        has_write_action = initialize or bool(updates)

        if not has_read_action and not has_write_action:
            created = ensure_env_file(env_file, example_file)
            values = read_env_values(env_file)
            updates = _prompt_config_values(values)
            write_env_values(env_file, updates)
            _clear_cached_settings()
            _echo_config_update(env_file, created, updates, show_secrets=show_secrets, as_json=as_json)
            return

        created = ensure_env_file(env_file, example_file) if has_write_action else False
        if updates:
            write_env_values(env_file, updates)
            _clear_cached_settings()

        values = read_env_values(env_file)
        if show_path and not (list_values or get_keys or updates or initialize):
            payload = {"env_file": str(env_file), "exists": env_file.exists()}
            echo_json(payload) if as_json else click.echo(str(env_file))
            return

        if get_keys:
            selected = {validate_env_key(key): values.get(validate_env_key(key), "") for key in get_keys}
            _echo_config_values(selected, show_secrets=show_secrets, as_json=as_json)
            return

        if list_values:
            selected = codewiki_values(values)
            _echo_config_values(selected, show_secrets=show_secrets, as_json=as_json, env_file=env_file)
            return

        _echo_config_update(env_file, created, updates, show_secrets=show_secrets, as_json=as_json)


def _config_updates(
    *,
    assignment_values: tuple[str, ...],
    profile: str,
    model: str | None,
    provider_type: str | None,
    endpoint: str | None,
    api_key: str | None,
    max_tokens: int | None,
    base_language: str | None,
    translation_languages: str | None,
) -> dict[str, str]:
    updates: dict[str, str] = {}
    for raw_assignment in assignment_values:
        assignment = parse_env_assignment(raw_assignment)
        updates[assignment.key] = assignment.value

    profile_options = {
        "MODEL": model,
        "PROVIDER_TYPE": provider_type,
        "ENDPOINT": endpoint,
        "API_KEY": api_key,
        "MAX_TOKENS": None if max_tokens is None else str(max_tokens),
    }
    for field, value in profile_options.items():
        if value is not None:
            updates[llm_profile_key(profile, field)] = value

    if base_language is not None:
        updates["CODEWIKI_WIKI_BASE_LANGUAGE"] = base_language
    if translation_languages is not None:
        updates["CODEWIKI_WIKI_TRANSLATION_LANGUAGES"] = translation_languages
    return updates


def _prompt_config_values(values: dict[str, str]) -> dict[str, str]:
    click.echo("Configuring CodeWiki environment variables.")
    updates: dict[str, str] = {}
    updates["CODEWIKI_LLM__MODE"] = click.prompt(
        "LLM mode",
        type=click.Choice(["sdk", "proxy"]),
        default=values.get("CODEWIKI_LLM__MODE") or "sdk",
    )
    updates["CODEWIKI_LLM__DEFAULT__MODEL"] = click.prompt(
        "Default model",
        default=values.get("CODEWIKI_LLM__DEFAULT__MODEL") or "provider/strong-coding-model",
    )
    updates["CODEWIKI_LLM__DEFAULT__PROVIDER_TYPE"] = click.prompt(
        "Default provider type",
        default=values.get("CODEWIKI_LLM__DEFAULT__PROVIDER_TYPE", ""),
        show_default=False,
    )
    updates["CODEWIKI_LLM__DEFAULT__ENDPOINT"] = click.prompt(
        "Default endpoint",
        default=values.get("CODEWIKI_LLM__DEFAULT__ENDPOINT", ""),
        show_default=False,
    )
    api_key = click.prompt(
        "Default API key (leave blank to keep current)",
        default="",
        hide_input=True,
        show_default=False,
    )
    if api_key:
        updates["CODEWIKI_LLM__DEFAULT__API_KEY"] = api_key

    updates["CODEWIKI_WIKI_BASE_LANGUAGE"] = click.prompt(
        "Wiki base language",
        default=values.get("CODEWIKI_WIKI_BASE_LANGUAGE") or "en",
    )
    updates["CODEWIKI_WIKI_TRANSLATION_LANGUAGES"] = click.prompt(
        "Wiki translation languages",
        default=values.get("CODEWIKI_WIKI_TRANSLATION_LANGUAGES", ""),
        show_default=False,
    )
    return updates


def _echo_config_update(
    env_file: Path,
    created: bool,
    updates: dict[str, str],
    *,
    show_secrets: bool,
    as_json: bool,
) -> None:
    payload = {
        "env_file": str(env_file),
        "created": created,
        "updated": mask_config_values(updates, show_secrets=show_secrets),
    }
    if as_json:
        echo_json(payload)
        return

    if created:
        click.echo(f"Created {env_file}")
    if updates:
        click.echo(f"Updated {env_file}")
        echo_table(
            ["key", "value"],
            [[key, value] for key, value in payload["updated"].items()],
        )
        return
    click.echo(f"No changes made to {env_file}")


def _echo_config_values(
    values: dict[str, str],
    *,
    show_secrets: bool,
    as_json: bool,
    env_file: Path | None = None,
) -> None:
    masked_values = mask_config_values(values, show_secrets=show_secrets)
    if as_json:
        payload: dict[str, object] = {"values": masked_values}
        if env_file is not None:
            payload["env_file"] = str(env_file)
        echo_json(payload)
        return

    if not masked_values:
        if env_file is None:
            click.echo("No values found.")
        else:
            click.echo(f"No CODEWIKI_* values configured in {env_file}.")
        return
    echo_table(["key", "value"], [[key, value] for key, value in masked_values.items()])


def _clear_cached_settings() -> None:
    get_settings.cache_clear()
    get_store.cache_clear()
