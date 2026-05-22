from typing import Any

from backend.app.config import Settings
from backend.app.database import DocCatalogRecord, DocPageRecord, CodeWikiStore, get_store
from backend.app.services.graphrag import GraphRAGRetriever
from backend.app.services.llm_gateway import LLMGateway
from backend.app.services.repo_context import RepositoryContextBuilder
from backend.app.services.wiki.catalog_generator import WikiCatalogGenerator
from backend.app.services.wiki.incremental_strategy import WikiIncrementalStrategy, WikiUpdateResult
from backend.app.services.wiki.language import WikiLanguageConfig, normalize_language
from backend.app.services.wiki.page_generator import PageGenerationResult, WikiPageGenerator
from backend.app.services.wiki.page_orchestrator import WikiPageOrchestrator
from backend.app.services.wiki.translation import WikiTranslationResult, WikiTranslator
from backend.app.services.wiki.translation_orchestrator import WikiTranslationOrchestrator


class WikiGenerator:
    """Facade for catalog, page, translation, and incremental wiki workflows."""

    def __init__(
        self,
        retriever: GraphRAGRetriever,
        llm: LLMGateway,
        *,
        store: CodeWikiStore | None = None,
        context_builder: RepositoryContextBuilder | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.retriever = retriever
        self.llm = llm
        self.store = store or get_store()
        self.settings = settings or Settings(_env_file=None)
        self.context_builder = context_builder or RepositoryContextBuilder()
        self.language_config = WikiLanguageConfig.from_settings(self.settings)
        self.incremental_strategy = WikiIncrementalStrategy()
        self.catalog_generator = WikiCatalogGenerator(
            self.retriever,
            self.llm,
            store=self.store,
            context_builder=self.context_builder,
        )
        self.page_generator = WikiPageGenerator(
            self.retriever,
            self.llm,
            store=self.store,
        )
        self.translator = WikiTranslator(self.llm, store=self.store)
        self.page_orchestrator = WikiPageOrchestrator(
            store=self.store,
            catalog_generator=self.catalog_generator,
            page_generator=self.page_generator,
            incremental_strategy=self.incremental_strategy,
        )
        self.translation_orchestrator = WikiTranslationOrchestrator(
            store=self.store,
            page_orchestrator=self.page_orchestrator,
            translator=self.translator,
            language_config=self.language_config,
            incremental_strategy=self.incremental_strategy,
        )

    async def generate_catalog(
        self,
        repo_id: str,
        *,
        language_code: str = "en",
    ) -> DocCatalogRecord:
        return await self.translation_orchestrator.generate_catalog(
            repo_id,
            language_code=language_code,
        )

    async def generate_all_pages(
        self,
        repo_id: str,
        *,
        language_code: str = "en",
    ) -> list[PageGenerationResult]:
        return await self.translation_orchestrator.generate_all_pages(
            repo_id,
            language_code=language_code,
        )

    async def update_pages(
        self,
        repo_id: str,
        *,
        language_code: str = "en",
    ) -> WikiUpdateResult:
        return await self.translation_orchestrator.update_pages(
            repo_id,
            language_code=language_code,
        )

    async def generate_page(
        self,
        repo_id: str,
        item: dict[str, Any],
        *,
        language_code: str = "en",
        parent_slug: str | None = None,
        child_pages: list[DocPageRecord] | None = None,
    ) -> PageGenerationResult:
        return await self.page_orchestrator.generate_page(
            repo_id,
            item,
            language_code=normalize_language(language_code),
            parent_slug=parent_slug,
            child_pages=child_pages,
        )

    async def regenerate_page(
        self,
        repo_id: str,
        slug: str,
        *,
        language_code: str = "en",
    ) -> PageGenerationResult:
        return await self.translation_orchestrator.regenerate_page(
            repo_id,
            slug,
            language_code=language_code,
        )

    async def translate_wiki(
        self,
        repo_id: str,
        *,
        target_language: str,
        source_language: str = "en",
    ) -> WikiTranslationResult:
        return await self.translation_orchestrator.translate_wiki(
            repo_id,
            source_language=source_language,
            target_language=target_language,
        )


__all__ = ["PageGenerationResult", "WikiGenerator", "WikiTranslationResult", "WikiUpdateResult"]
