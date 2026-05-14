from typing import Any

from backend.app.database import DocCatalogRecord, SQLiteStore, get_store
from backend.app.services.graphrag import GraphRAGRetriever
from backend.app.services.llm_gateway import LLMGateway
from backend.app.services.repo_context import RepositoryContextBuilder
from backend.app.services.wiki.catalog import _catalog_items_for_generation, _slugify
from backend.app.services.wiki.catalog_generator import WikiCatalogGenerator
from backend.app.services.wiki.page_generator import PageGenerationResult, WikiPageGenerator


class WikiGenerator:
    def __init__(
        self,
        retriever: GraphRAGRetriever,
        llm: LLMGateway,
        *,
        store: SQLiteStore | None = None,
        context_builder: RepositoryContextBuilder | None = None,
    ) -> None:
        self.retriever = retriever
        self.llm = llm
        self.store = store or get_store()
        self.context_builder = context_builder or RepositoryContextBuilder()
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

    async def generate_catalog(self, repo_id: str) -> DocCatalogRecord:
        return await self.catalog_generator.generate_catalog(repo_id)

    async def generate_all_pages(self, repo_id: str) -> list[PageGenerationResult]:
        catalog = self.store.get_latest_doc_catalog(repo_id)
        if catalog is None:
            catalog = await self.generate_catalog(repo_id)
        results: list[PageGenerationResult] = []
        for item, parent_slug in _catalog_items_for_generation(catalog.structure.get("items", [])):
            results.append(await self.generate_page(repo_id, item, parent_slug=parent_slug))
        self.store.delete_doc_pages_not_in(
            repo_id,
            [result.page.slug for result in results],
        )
        return results

    async def generate_page(
        self,
        repo_id: str,
        item: dict[str, Any],
        *,
        parent_slug: str | None = None,
    ) -> PageGenerationResult:
        return await self.page_generator.generate_page(repo_id, item, parent_slug=parent_slug)

    async def regenerate_page(self, repo_id: str, slug: str) -> PageGenerationResult:
        catalog = self.store.get_latest_doc_catalog(repo_id)
        if catalog is None:
            raise ValueError("Generate a catalog before regenerating pages.")
        for item, parent_slug in _catalog_items_for_generation(catalog.structure.get("items", [])):
            if _slugify(str(item.get("slug") or item.get("path") or item.get("title") or "")) == slug:
                return await self.generate_page(repo_id, item, parent_slug=parent_slug)
        raise ValueError(f"Catalog page not found: {slug}")


__all__ = ["PageGenerationResult", "WikiGenerator"]
