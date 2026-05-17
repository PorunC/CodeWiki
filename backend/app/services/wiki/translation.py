import uuid
from dataclasses import dataclass
from typing import Any

from backend.app.database import DocCatalogRecord, DocPageRecord, SQLiteStore
from backend.app.services.llm_gateway import LLMGateway
from backend.app.services.llm_operations import CachedLLMService, LLMOperation
from backend.app.services.wiki.catalog import _validate_catalog_payload
from backend.app.services.wiki.language import normalize_language
from backend.app.services.wiki.prompts import _json_object
from backend.app.services.wiki.translation_support import (
    CatalogTitleTranslationMapper,
    TranslationPromptBuilder,
    TranslationResponseValidator,
    TranslationStyleGuide,
)
from backend.app.services.wiki.utils import ordered_unique

TRANSLATION_ATTEMPTS = 3
TRANSLATION_PROMPT_VERSION = "translation:wiki:v3"


@dataclass(frozen=True)
class WikiTranslationResult:
    catalog: DocCatalogRecord
    pages: list[DocPageRecord]
    source_language: str
    target_language: str


class WikiTranslator:
    def __init__(self, llm: LLMGateway, *, store: SQLiteStore) -> None:
        self.llm = llm
        self.store = store
        self.llm_service = CachedLLMService(store=self.store, llm=self.llm)
        self.catalog_title_mapper = CatalogTitleTranslationMapper()
        self.prompt_builder = TranslationPromptBuilder()
        self.response_validator = TranslationResponseValidator()
        self.style_guide = TranslationStyleGuide()

    async def translate_wiki(
        self,
        repo_id: str,
        *,
        source_language: str,
        target_language: str,
    ) -> WikiTranslationResult:
        source_language = normalize_language(source_language)
        target_language = normalize_language(target_language)
        if source_language == target_language:
            raise ValueError("source_language and target_language must be different.")

        source_catalog = self.store.get_latest_doc_catalog(
            repo_id,
            language_code=source_language,
        )
        if source_catalog is None:
            raise ValueError(f"Source catalog not found for language: {source_language}")

        translated_catalog = await self._translate_catalog(
            source_catalog,
            source_language=source_language,
            target_language=target_language,
        )
        translated_pages: list[DocPageRecord] = []
        for page in self.store.list_doc_pages(repo_id, language_code=source_language):
            translated_pages.append(
                await self._translate_page(
                    page,
                    source_language=source_language,
                    target_language=target_language,
                )
            )
        return WikiTranslationResult(
            catalog=translated_catalog,
            pages=translated_pages,
            source_language=source_language,
            target_language=target_language,
        )

    async def ensure_translated_catalog(
        self,
        repo_id: str,
        *,
        source_language: str,
        target_language: str,
    ) -> DocCatalogRecord:
        source_language = normalize_language(source_language)
        target_language = normalize_language(target_language)
        source_catalog = self.store.get_latest_doc_catalog(repo_id, language_code=source_language)
        if source_catalog is None:
            raise ValueError(f"Source catalog not found for language: {source_language}")
        catalog = self.store.get_latest_doc_catalog(repo_id, language_code=target_language)
        if catalog is not None:
            target_paths = self.catalog_title_mapper.paths(catalog.structure.get("items", []))
            source_paths = self.catalog_title_mapper.paths(source_catalog.structure.get("items", []))
            if target_paths == source_paths:
                return catalog
        return await self._translate_catalog(
            source_catalog,
            source_language=source_language,
            target_language=target_language,
        )

    async def translate_page_slugs(
        self,
        repo_id: str,
        *,
        source_language: str,
        target_language: str,
        slugs: list[str],
    ) -> list[DocPageRecord]:
        source_language = normalize_language(source_language)
        target_language = normalize_language(target_language)
        requested_slugs = ordered_unique(slugs)
        if not requested_slugs:
            return []

        source_pages_by_slug = {
            page.slug: page
            for page in self.store.list_doc_pages(repo_id, language_code=source_language)
        }
        translated_pages: list[DocPageRecord] = []
        for slug in requested_slugs:
            page = source_pages_by_slug.get(slug)
            if page is None:
                continue
            translated_pages.append(
                await self._translate_page(
                    page,
                    source_language=source_language,
                    target_language=target_language,
                )
            )
        return translated_pages

    async def _translate_catalog(
        self,
        catalog: DocCatalogRecord,
        *,
        source_language: str,
        target_language: str,
    ) -> DocCatalogRecord:
        title_entries = self.catalog_title_mapper.title_entries(catalog.structure.get("items", []))
        payload = {
            "content_type": "catalog",
            "source_language": source_language,
            "target_language": target_language,
            "title": catalog.title,
            "items": title_entries,
            "style_guide": self.style_guide.for_language(target_language),
            "rules": [
                "Translate only human-facing title text.",
                "For Chinese targets, use concise natural Simplified Chinese documentation titles.",
                "Do not translate slugs, paths, topics, source_hints, or code identifiers.",
                "Return JSON with title and items containing path and title.",
            ],
        }
        response = await self._complete_translation_json(
            catalog.repo_id,
            payload,
            cache_parts=("catalog", catalog.id, source_language, target_language),
            content_type="catalog",
        )
        translated_structure = {
            "items": self.catalog_title_mapper.apply(
                catalog.structure.get("items", []),
                response.get("items"),
            )
        }
        _validate_catalog_payload(translated_structure)
        return self.store.save_doc_catalog(
            catalog.repo_id,
            title=str(response.get("title") or catalog.title),
            structure=translated_structure,
            language_code=target_language,
        )

    async def _translate_page(
        self,
        page: DocPageRecord,
        *,
        source_language: str,
        target_language: str,
    ) -> DocPageRecord:
        payload = {
            "content_type": "page",
            "source_language": source_language,
            "target_language": target_language,
            "title": page.title,
            "markdown": page.markdown,
            "source_refs": page.source_refs,
            "style_guide": self.style_guide.for_language(target_language),
            "rules": [
                "Translate prose and headings to the target language with natural local writing.",
                "For Chinese targets, rewrite awkward literal phrasing into fluent Chinese technical prose.",
                "Keep code blocks, inline code, file paths, URLs, anchors, and identifiers unchanged.",
                "Keep Markdown structure and links valid.",
                "Do not remove source citations or source sections.",
                "Return JSON with title and markdown.",
            ],
        }
        response = await self._complete_translation_json(
            page.repo_id,
            payload,
            cache_parts=("page", page.id, source_language, target_language),
            content_type="page",
        )
        translated_page = DocPageRecord(
            id=uuid.uuid4().hex,
            repo_id=page.repo_id,
            language_code=target_language,
            slug=page.slug,
            title=str(response.get("title") or page.title),
            parent_slug=page.parent_slug,
            markdown=str(response.get("markdown") or page.markdown),
            source_refs=page.source_refs,
            graph_refs=page.graph_refs,
            status=page.status,
            updated_at=None,
        )
        return self.store.upsert_doc_page(translated_page)

    async def _complete_translation_json(
        self,
        repo_id: str,
        payload: dict[str, Any],
        *,
        cache_parts: tuple[object, ...],
        content_type: str,
    ) -> dict[str, Any]:
        attempt_payload = payload
        validation_errors: list[str] = []
        for attempt in range(TRANSLATION_ATTEMPTS):
            completion = await self.llm_service.complete(
                repo_id,
                LLMOperation(
                    task_type="translation",
                    messages=self.prompt_builder.messages(attempt_payload, validation_errors),
                    input_payload=attempt_payload,
                    cache_namespace="translation:v3",
                    cache_parts=(*cache_parts, "attempt", attempt + 1),
                    model_alias="translation",
                    prompt_version=TRANSLATION_PROMPT_VERSION,
                    response_format="json_object",
                ),
            )
            try:
                response = _json_object(completion.result.content)
                self.response_validator.validate(response, content_type=content_type)
                return response
            except ValueError as exc:
                validation_errors = [str(exc)]
                self.store.update_llm_run_status(
                    completion.run.id,
                    status="error",
                    error=str(exc),
                )
                attempt_payload = self.prompt_builder.repair_payload(
                    payload,
                    completion.result.content,
                    validation_errors,
                )

        raise ValueError(
            f"Translation LLM did not return a valid {content_type} JSON object "
            "after repair attempts: "
            + "; ".join(validation_errors)
        )
