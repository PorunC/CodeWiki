import asyncio
from dataclasses import dataclass
from typing import Any

from backend.app.database import DocCatalogRecord, DocPageRecord, SQLiteStore, get_store
from backend.app.services.graphrag import GraphRAGRetriever
from backend.app.services.llm_gateway import LLMGateway
from backend.app.services.repo_context import RepositoryContextBuilder
from backend.app.services.wiki.catalog import _catalog_items_for_generation, _slugify
from backend.app.services.wiki.catalog_generator import WikiCatalogGenerator
from backend.app.services.wiki.page_generator import PageGenerationResult, WikiPageGenerator

PAGE_GENERATION_CONCURRENCY = 3


@dataclass(frozen=True)
class _GenerationNode:
    item: dict[str, Any]
    parent_slug: str | None
    slug: str
    depth: int
    order: int
    has_children: bool


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
        nodes = _generation_nodes(catalog.structure.get("items", []))
        results_by_slug: dict[str, PageGenerationResult] = {}
        semaphore = asyncio.Semaphore(PAGE_GENERATION_CONCURRENCY)

        async def generate_leaf(node: _GenerationNode) -> None:
            async with semaphore:
                results_by_slug[node.slug] = await self.generate_page(
                    repo_id,
                    node.item,
                    parent_slug=node.parent_slug,
                )

        await asyncio.gather(*(generate_leaf(node) for node in nodes if not node.has_children))

        parent_nodes = sorted(
            (node for node in nodes if node.has_children),
            key=lambda node: (-node.depth, node.order),
        )
        for node in parent_nodes:
            child_pages = _child_pages_for_item(node.item, results_by_slug)
            results_by_slug[node.slug] = await self.generate_page(
                repo_id,
                node.item,
                parent_slug=node.parent_slug,
                child_pages=child_pages,
            )

        results = [
            results_by_slug[node.slug]
            for node in nodes
            if node.slug in results_by_slug
        ]
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
        child_pages: list[DocPageRecord] | None = None,
    ) -> PageGenerationResult:
        return await self.page_generator.generate_page(
            repo_id,
            item,
            parent_slug=parent_slug,
            child_pages=child_pages,
        )

    async def regenerate_page(self, repo_id: str, slug: str) -> PageGenerationResult:
        catalog = self.store.get_latest_doc_catalog(repo_id)
        if catalog is None:
            raise ValueError("Generate a catalog before regenerating pages.")
        for item, parent_slug in _catalog_items_for_generation(catalog.structure.get("items", [])):
            if _slugify(str(item.get("slug") or item.get("path") or item.get("title") or "")) == slug:
                child_pages = []
                if _has_children(item):
                    child_results = await self._generate_descendant_pages(repo_id, item)
                    child_pages = _child_pages_for_item(
                        item,
                        {result.page.slug: result for result in child_results},
                    )
                return await self.generate_page(
                    repo_id,
                    item,
                    parent_slug=parent_slug,
                    child_pages=child_pages,
                )
        raise ValueError(f"Catalog page not found: {slug}")

    async def _generate_descendant_pages(
        self,
        repo_id: str,
        item: dict[str, Any],
    ) -> list[PageGenerationResult]:
        children = _item_children(item)
        nodes = _generation_nodes(children, parent_slug=_catalog_slug(item), depth=1)
        results: list[PageGenerationResult] = []
        results_by_slug: dict[str, PageGenerationResult] = {}
        semaphore = asyncio.Semaphore(PAGE_GENERATION_CONCURRENCY)

        async def generate_leaf(node: _GenerationNode) -> None:
            async with semaphore:
                results_by_slug[node.slug] = await self.generate_page(
                    repo_id,
                    node.item,
                    parent_slug=node.parent_slug,
                )

        await asyncio.gather(*(generate_leaf(node) for node in nodes if not node.has_children))
        for node in sorted(
            (node for node in nodes if node.has_children),
            key=lambda node: (-node.depth, node.order),
        ):
            results_by_slug[node.slug] = await self.generate_page(
                repo_id,
                node.item,
                parent_slug=node.parent_slug,
                child_pages=_child_pages_for_item(node.item, results_by_slug),
            )

        for node in nodes:
            if node.slug in results_by_slug:
                results.append(results_by_slug[node.slug])
        return results


__all__ = ["PageGenerationResult", "WikiGenerator"]


def _generation_nodes(
    items: list[Any],
    *,
    parent_slug: str | None = None,
    depth: int = 0,
) -> list[_GenerationNode]:
    nodes: list[_GenerationNode] = []

    def visit(raw_items: list[Any], current_parent_slug: str | None, current_depth: int) -> None:
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            slug = _catalog_slug(item)
            children = _item_children(item)
            has_children = bool(children)
            kind = str(item.get("kind") or "").lower()
            if kind in {"page", "category"} or not has_children:
                nodes.append(
                    _GenerationNode(
                        item=item,
                        parent_slug=current_parent_slug,
                        slug=slug,
                        depth=current_depth,
                        order=len(nodes),
                        has_children=has_children,
                    )
                )
            visit(children, slug, current_depth + 1)

    visit(items, parent_slug, depth)
    return nodes


def _child_pages_for_item(
    item: dict[str, Any],
    results_by_slug: dict[str, PageGenerationResult],
) -> list[DocPageRecord]:
    pages: list[DocPageRecord] = []
    for child in _item_children(item):
        result = results_by_slug.get(_catalog_slug(child))
        if result is not None:
            pages.append(result.page)
    return pages


def _has_children(item: dict[str, Any]) -> bool:
    return bool(_item_children(item))


def _item_children(item: dict[str, Any]) -> list[dict[str, Any]]:
    children = item.get("children") or []
    if not isinstance(children, list):
        return []
    return [child for child in children if isinstance(child, dict)]


def _catalog_slug(item: dict[str, Any]) -> str:
    return _slugify(str(item.get("slug") or item.get("path") or item.get("title") or ""))
