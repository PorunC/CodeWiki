import asyncio
from typing import Any

from backend.app.database import DocPageRecord, CodeWikiStore
from backend.app.services.wiki.catalog_generator import WikiCatalogGenerator
from backend.app.services.wiki.incremental_strategy import (
    WikiIncrementalStrategy,
    WikiUpdateResult,
)
from backend.app.services.wiki.page_generator import PageGenerationResult, WikiPageGenerator
from backend.app.services.wiki.tree import (
    GenerationNode,
    catalog_slug,
    child_page_records_for_item,
    child_pages_for_item,
    generation_nodes,
    has_children,
    item_children,
)

PAGE_GENERATION_CONCURRENCY = 3


class WikiPageOrchestrator:
    def __init__(
        self,
        *,
        store: CodeWikiStore,
        catalog_generator: WikiCatalogGenerator,
        page_generator: WikiPageGenerator,
        incremental_strategy: WikiIncrementalStrategy | None = None,
        concurrency: int = PAGE_GENERATION_CONCURRENCY,
    ) -> None:
        self.store = store
        self.catalog_generator = catalog_generator
        self.page_generator = page_generator
        self.incremental_strategy = incremental_strategy or WikiIncrementalStrategy()
        self.concurrency = concurrency

    async def generate_all_pages(
        self,
        repo_id: str,
        *,
        language_code: str,
    ) -> list[PageGenerationResult]:
        catalog = self.store.get_latest_doc_catalog(repo_id, language_code=language_code)
        if catalog is None:
            catalog = await self.catalog_generator.generate_catalog(
                repo_id,
                language_code=language_code,
            )
        nodes = generation_nodes(catalog.structure.get("items", []))
        results_by_slug = await self._generate_nodes(repo_id, nodes, language_code=language_code)
        results = [results_by_slug[node.slug] for node in nodes if node.slug in results_by_slug]
        self.store.delete_doc_pages_not_in(
            repo_id,
            [result.page.slug for result in results],
            language_code=language_code,
        )
        return results

    async def update_pages(
        self,
        repo_id: str,
        *,
        language_code: str,
    ) -> WikiUpdateResult:
        catalog = self.store.get_latest_doc_catalog(repo_id, language_code=language_code)
        if catalog is None:
            catalog = await self.catalog_generator.generate_catalog(
                repo_id,
                language_code=language_code,
            )

        nodes = generation_nodes(catalog.structure.get("items", []))
        existing_by_slug = {
            page.slug: page
            for page in self.store.list_doc_pages(repo_id, language_code=language_code)
        }
        dirty_plan = self.incremental_strategy.plan_dirty_pages(nodes, existing_by_slug)
        results_by_slug = await self._generate_nodes(
            repo_id,
            [node for node in nodes if node.slug in dirty_plan.dirty_slugs],
            language_code=language_code,
            existing_pages_by_slug=existing_by_slug,
        )

        catalog_slugs = [node.slug for node in nodes]
        deleted_page_count = self.store.delete_doc_pages_not_in(
            repo_id,
            catalog_slugs,
            language_code=language_code,
        )
        generated_slugs = [node.slug for node in nodes if node.slug in results_by_slug]
        reused_pages = [
            existing_by_slug[node.slug]
            for node in nodes
            if node.slug not in dirty_plan.dirty_slugs and node.slug in existing_by_slug
        ]
        return WikiUpdateResult(
            repo_id=repo_id,
            language_code=language_code,
            results=[results_by_slug[slug] for slug in generated_slugs],
            reused_pages=reused_pages,
            stale_slugs=dirty_plan.stale_slugs,
            missing_slugs=dirty_plan.missing_slugs,
            metadata_changed_slugs=dirty_plan.metadata_changed_slugs,
            generated_slugs=generated_slugs,
            deleted_page_count=deleted_page_count,
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
        return await self.page_generator.generate_page(
            repo_id,
            item,
            language_code=language_code,
            parent_slug=parent_slug,
            child_pages=child_pages,
        )

    async def regenerate_page(
        self,
        repo_id: str,
        slug: str,
        *,
        language_code: str,
    ) -> PageGenerationResult:
        catalog = self.store.get_latest_doc_catalog(repo_id, language_code=language_code)
        if catalog is None:
            raise ValueError("Generate a catalog before regenerating pages.")
        for node in generation_nodes(catalog.structure.get("items", [])):
            if node.slug != slug:
                continue
            child_pages = []
            if has_children(node.item):
                child_results = await self.generate_descendant_pages(
                    repo_id,
                    node.item,
                    language_code=language_code,
                )
                child_pages = child_pages_for_item(
                    node.item,
                    {result.page.slug: result for result in child_results},
                )
            return await self.generate_page(
                repo_id,
                node.item,
                language_code=language_code,
                parent_slug=node.parent_slug,
                child_pages=child_pages,
            )
        raise ValueError(f"Catalog page not found: {slug}")

    async def generate_descendant_pages(
        self,
        repo_id: str,
        item: dict[str, Any],
        *,
        language_code: str = "en",
    ) -> list[PageGenerationResult]:
        children = item_children(item)
        nodes = generation_nodes(children, parent_slug=catalog_slug(item), depth=1)
        results_by_slug = await self._generate_nodes(repo_id, nodes, language_code=language_code)
        return [results_by_slug[node.slug] for node in nodes if node.slug in results_by_slug]

    async def _generate_nodes(
        self,
        repo_id: str,
        nodes: list[GenerationNode],
        *,
        language_code: str,
        existing_pages_by_slug: dict[str, DocPageRecord] | None = None,
    ) -> dict[str, PageGenerationResult]:
        results_by_slug: dict[str, PageGenerationResult] = {}
        page_records_by_slug = dict(existing_pages_by_slug or {})
        semaphore = asyncio.Semaphore(self.concurrency)

        async def generate_leaf(node: GenerationNode) -> None:
            async with semaphore:
                result = await self.generate_page(
                    repo_id,
                    node.item,
                    language_code=language_code,
                    parent_slug=node.parent_slug,
                )
                results_by_slug[node.slug] = result
                page_records_by_slug[node.slug] = result.page

        await asyncio.gather(*(generate_leaf(node) for node in nodes if not node.has_children))

        for node in sorted(
            (node for node in nodes if node.has_children),
            key=lambda node: (-node.depth, node.order),
        ):
            result = await self.generate_page(
                repo_id,
                node.item,
                language_code=language_code,
                parent_slug=node.parent_slug,
                child_pages=child_page_records_for_item(node.item, page_records_by_slug),
            )
            results_by_slug[node.slug] = result
            page_records_by_slug[node.slug] = result.page
        return results_by_slug
