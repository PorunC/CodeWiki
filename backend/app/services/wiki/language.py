from dataclasses import dataclass

from backend.app.config import Settings


@dataclass(frozen=True)
class WikiLanguageConfig:
    base_language: str
    translation_languages: list[str]

    @classmethod
    def from_settings(cls, settings: Settings) -> "WikiLanguageConfig":
        return cls(
            base_language=normalize_language(settings.wiki_base_language),
            translation_languages=parse_translation_languages(settings.wiki_translation_languages),
        )


def parse_translation_languages(raw_languages: str | None) -> list[str]:
    languages: list[str] = []
    for raw_language in (raw_languages or "").split(","):
        language_code = normalize_language(raw_language)
        if raw_language.strip() and language_code not in languages:
            languages.append(language_code)
    return languages


def normalize_language(language_code: str | None) -> str:
    return (language_code or "en").strip().lower() or "en"

