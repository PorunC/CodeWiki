from backend.app.database import DocCatalogRecord, DocPageRecord, CodeWikiStore
from backend.app.services.wiki.incremental_strategy import (
    WikiIncrementalStrategy,
    WikiUpdateResult,
)
from backend.app.services.wiki.language import WikiLanguageConfig, normalize_language
from backend.app.services.wiki.page_generator import PageGenerationResult
from backend.app.services.wiki.page_orchestrator import WikiPageOrchestrator
from backend.app.services.wiki.translation import WikiTranslationResult, WikiTranslator


class WikiTranslationOrchestrator:
    def __init__(
        self,
        *,
        store: CodeWikiStore,
        page_orchestrator: WikiPageOrchestrator,
        translator: WikiTranslator,
        language_config: WikiLanguageConfig,
        incremental_strategy: WikiIncrementalStrategy | None = None,
    ) -> None:
        self.store = store
        self.page_orchestrator = page_orchestrator
        self.translator = translator
        self.language_config = language_config
        self.incremental_strategy = incremental_strategy or WikiIncrementalStrategy()

    async def generate_catalog(
        self,
        repo_id: str,
        *,
        language_code: str,
    ) -> DocCatalogRecord:
        language_code = normalize_language(language_code)
        base_language = self.language_config.base_language
        if language_code == base_language:
            return await self.page_orchestrator.catalog_generator.generate_catalog(
                repo_id,
                language_code=language_code,
            )

        await self.ensure_base_catalog(repo_id)
        return (
            await self.translate_wiki(
                repo_id,
                source_language=base_language,
                target_language=language_code,
            )
        ).catalog

    async def generate_all_pages(
        self,
        repo_id: str,
        *,
        language_code: str,
    ) -> list[PageGenerationResult]:
        language_code = normalize_language(language_code)
        base_language = self.language_config.base_language
        if language_code != base_language:
            await self.ensure_base_pages(repo_id)
            translated = await self.translate_wiki(
                repo_id,
                source_language=base_language,
                target_language=language_code,
            )
            return [
                PageGenerationResult(page=page, validation_errors=_translation_validation_errors(page))
                for page in translated.pages
            ]

        results = await self.page_orchestrator.generate_all_pages(
            repo_id,
            language_code=base_language,
        )
        await self.translate_configured_languages(repo_id)
        return results

    async def update_pages(
        self,
        repo_id: str,
        *,
        language_code: str,
    ) -> WikiUpdateResult:
        language_code = normalize_language(language_code)
        base_language = self.language_config.base_language
        if language_code != base_language:
            return await self._update_translated_pages(
                repo_id,
                source_language=base_language,
                target_language=language_code,
            )

        update = await self.page_orchestrator.update_pages(
            repo_id,
            language_code=base_language,
        )
        await self.translate_configured_languages_for_slugs(repo_id, update.generated_slugs)
        return update

    async def regenerate_page(
        self,
        repo_id: str,
        slug: str,
        *,
        language_code: str,
    ) -> PageGenerationResult:
        language_code = normalize_language(language_code)
        base_language = self.language_config.base_language
        if language_code != base_language:
            await self.page_orchestrator.regenerate_page(
                repo_id,
                slug,
                language_code=base_language,
            )
            await self.translator.ensure_translated_catalog(
                repo_id,
                source_language=base_language,
                target_language=language_code,
            )
            translated_pages = await self.translator.translate_page_slugs(
                repo_id,
                source_language=base_language,
                target_language=language_code,
                slugs=[slug],
            )
            page = next((page for page in translated_pages if page.slug == slug), None)
            if page is None:
                raise ValueError(f"Translated catalog page not found: {slug}")
            return PageGenerationResult(page=page, validation_errors=_translation_validation_errors(page))

        result = await self.page_orchestrator.regenerate_page(
            repo_id,
            slug,
            language_code=base_language,
        )
        await self.translate_configured_languages(repo_id)
        return result

    async def translate_wiki(
        self,
        repo_id: str,
        *,
        target_language: str,
        source_language: str = "en",
    ) -> WikiTranslationResult:
        return await self.translator.translate_wiki(
            repo_id,
            source_language=source_language,
            target_language=target_language,
        )

    async def ensure_base_catalog(self, repo_id: str) -> DocCatalogRecord:
        base_language = self.language_config.base_language
        catalog = self.store.get_latest_doc_catalog(repo_id, language_code=base_language)
        if catalog is not None:
            return catalog
        return await self.page_orchestrator.catalog_generator.generate_catalog(
            repo_id,
            language_code=base_language,
        )

    async def ensure_base_pages(self, repo_id: str) -> list[PageGenerationResult]:
        base_language = self.language_config.base_language
        await self.ensure_base_catalog(repo_id)
        pages = self.store.list_doc_pages(repo_id, language_code=base_language)
        if pages:
            return [PageGenerationResult(page=page, validation_errors=[]) for page in pages]
        return await self.page_orchestrator.generate_all_pages(
            repo_id,
            language_code=base_language,
        )

    async def translate_configured_languages(self, repo_id: str) -> None:
        base_language = self.language_config.base_language
        for language_code in self.language_config.translation_languages:
            if language_code == base_language:
                continue
            await self.translate_wiki(
                repo_id,
                source_language=base_language,
                target_language=language_code,
            )

    async def translate_configured_languages_for_slugs(
        self,
        repo_id: str,
        slugs: list[str],
    ) -> None:
        if not slugs:
            return
        base_language = self.language_config.base_language
        for language_code in self.language_config.translation_languages:
            if language_code == base_language:
                continue
            await self.translator.ensure_translated_catalog(
                repo_id,
                source_language=base_language,
                target_language=language_code,
            )
            await self.translator.translate_page_slugs(
                repo_id,
                source_language=base_language,
                target_language=language_code,
                slugs=slugs,
            )

    async def _update_translated_pages(
        self,
        repo_id: str,
        *,
        source_language: str,
        target_language: str,
    ) -> WikiUpdateResult:
        base_update = await self.page_orchestrator.update_pages(
            repo_id,
            language_code=source_language,
        )
        await self.translator.ensure_translated_catalog(
            repo_id,
            source_language=source_language,
            target_language=target_language,
        )
        source_pages = self.store.list_doc_pages(repo_id, language_code=source_language)
        source_slugs = [page.slug for page in source_pages]
        existing_target_by_slug = {
            page.slug: page
            for page in self.store.list_doc_pages(repo_id, language_code=target_language)
        }
        target_dirty_slugs = self.incremental_strategy.translated_dirty_slugs(
            source_slugs=source_slugs,
            existing_target_by_slug=existing_target_by_slug,
            base_generated_slugs=base_update.generated_slugs,
        )
        translated_pages = await self.translator.translate_page_slugs(
            repo_id,
            source_language=source_language,
            target_language=target_language,
            slugs=target_dirty_slugs,
        )
        deleted_page_count = self.store.delete_doc_pages_not_in(
            repo_id,
            source_slugs,
            language_code=target_language,
        )
        results = [
            PageGenerationResult(page=page, validation_errors=_translation_validation_errors(page))
            for page in translated_pages
        ]
        dirty_set = set(target_dirty_slugs)
        reused_pages = [
            existing_target_by_slug[slug]
            for slug in source_slugs
            if slug not in dirty_set and slug in existing_target_by_slug
        ]
        return WikiUpdateResult(
            repo_id=repo_id,
            language_code=target_language,
            results=results,
            reused_pages=reused_pages,
            stale_slugs=[
                slug
                for slug, page in existing_target_by_slug.items()
                if slug in source_slugs and page.status != "generated"
            ],
            missing_slugs=[slug for slug in source_slugs if slug not in existing_target_by_slug],
            metadata_changed_slugs=[],
            generated_slugs=[page.slug for page in translated_pages],
            deleted_page_count=deleted_page_count,
        )


def _translation_validation_errors(page: DocPageRecord) -> list[str]:
    if page.status != "draft":
        return []
    return ["Translation failed; page was saved as a draft."]
