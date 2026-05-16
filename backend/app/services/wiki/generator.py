import asyncio
from dataclasses import dataclass
from typing import Any

from backend.app.config import Settings
from backend.app.database import DocCatalogRecord, DocPageRecord, SQLiteStore, get_store
from backend.app.services.graphrag import GraphRAGRetriever
from backend.app.services.llm_gateway import LLMGateway
from backend.app.services.repo_context import RepositoryContextBuilder
from backend.app.services.wiki.catalog import _catalog_items_for_generation, _slugify
from backend.app.services.wiki.catalog_generator import WikiCatalogGenerator
from backend.app.services.wiki.page_generator import PageGenerationResult, WikiPageGenerator
from backend.app.services.wiki.translation import WikiTranslationResult, WikiTranslator

PAGE_GENERATION_CONCURRENCY = 3


@dataclass(frozen=True)
class _GenerationNode:
    item: dict[str, Any]
    parent_slug: str | None
    slug: str
    depth: int
    order: int
    has_children: bool


@dataclass(frozen=True)
class WikiUpdateResult:
    repo_id: str
    language_code: str
    results: list[PageGenerationResult]
    reused_pages: list[DocPageRecord]
    stale_slugs: list[str]
    missing_slugs: list[str]
    metadata_changed_slugs: list[str]
    generated_slugs: list[str]
    deleted_page_count: int


class WikiGenerator:
    def __init__(
        self,
        retriever: GraphRAGRetriever,
        llm: LLMGateway,
        *,
        store: SQLiteStore | None = None,
        context_builder: RepositoryContextBuilder | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.retriever = retriever
        self.llm = llm
        self.store = store or get_store()
        self.settings = settings or Settings(_env_file=None)
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
        self.translator = WikiTranslator(self.llm, store=self.store)

    async def generate_catalog(
        self,
        repo_id: str,
        *,
        language_code: str = "en",
    ) -> DocCatalogRecord:
        language_code = _normalize_language(language_code)
        base_language = self._base_language()
        if language_code == base_language:
            return await self.catalog_generator.generate_catalog(repo_id, language_code=language_code)

        await self._ensure_base_catalog(repo_id)
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
        language_code: str = "en",
    ) -> list[PageGenerationResult]:
        language_code = _normalize_language(language_code)
        base_language = self._base_language()
        if language_code != base_language:
            await self._ensure_base_pages(repo_id)
            translated = await self.translate_wiki(
                repo_id,
                source_language=base_language,
                target_language=language_code,
            )
            return [
                PageGenerationResult(page=page, validation_errors=[])
                for page in translated.pages
            ]

        results = await self._generate_all_pages_for_language(repo_id, language_code=base_language)
        await self._translate_configured_languages(repo_id)
        return results

    async def update_pages(
        self,
        repo_id: str,
        *,
        language_code: str = "en",
    ) -> WikiUpdateResult:
        language_code = _normalize_language(language_code)
        base_language = self._base_language()
        if language_code != base_language:
            return await self._update_translated_pages(
                repo_id,
                source_language=base_language,
                target_language=language_code,
            )

        update = await self._update_pages_for_language(repo_id, language_code=base_language)
        await self._translate_configured_languages_for_slugs(repo_id, update.generated_slugs)
        return update

    async def _generate_all_pages_for_language(
        self,
        repo_id: str,
        *,
        language_code: str,
    ) -> list[PageGenerationResult]:
        catalog = self.store.get_latest_doc_catalog(repo_id, language_code=language_code)
        if catalog is None:
            catalog = await self.generate_catalog(repo_id, language_code=language_code)
        nodes = _generation_nodes(catalog.structure.get("items", []))
        results_by_slug: dict[str, PageGenerationResult] = {}
        semaphore = asyncio.Semaphore(PAGE_GENERATION_CONCURRENCY)

        async def generate_leaf(node: _GenerationNode) -> None:
            async with semaphore:
                results_by_slug[node.slug] = await self.generate_page(
                    repo_id,
                    node.item,
                    language_code=language_code,
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
                language_code=language_code,
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
            language_code=language_code,
        )
        return results

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
        language_code: str = "en",
    ) -> PageGenerationResult:
        language_code = _normalize_language(language_code)
        base_language = self._base_language()
        if language_code != base_language:
            await self._regenerate_page_for_language(repo_id, slug, language_code=base_language)
            translated = await self.translate_wiki(
                repo_id,
                source_language=base_language,
                target_language=language_code,
            )
            page = next((page for page in translated.pages if page.slug == slug), None)
            if page is None:
                raise ValueError(f"Translated catalog page not found: {slug}")
            return PageGenerationResult(page=page, validation_errors=[])

        result = await self._regenerate_page_for_language(
            repo_id,
            slug,
            language_code=base_language,
        )
        await self._translate_configured_languages(repo_id)
        return result

    async def _update_pages_for_language(
        self,
        repo_id: str,
        *,
        language_code: str,
    ) -> WikiUpdateResult:
        catalog = self.store.get_latest_doc_catalog(repo_id, language_code=language_code)
        if catalog is None:
            catalog = await self.generate_catalog(repo_id, language_code=language_code)

        nodes = _generation_nodes(catalog.structure.get("items", []))
        existing_by_slug = {
            page.slug: page
            for page in self.store.list_doc_pages(repo_id, language_code=language_code)
        }
        page_records_by_slug = dict(existing_by_slug)
        dirty_slugs, stale_slugs, missing_slugs, metadata_changed_slugs = _dirty_wiki_page_slugs(
            nodes,
            existing_by_slug,
        )
        results_by_slug: dict[str, PageGenerationResult] = {}
        semaphore = asyncio.Semaphore(PAGE_GENERATION_CONCURRENCY)

        async def generate_leaf(node: _GenerationNode) -> None:
            async with semaphore:
                result = await self.generate_page(
                    repo_id,
                    node.item,
                    language_code=language_code,
                    parent_slug=node.parent_slug,
                )
                results_by_slug[node.slug] = result
                page_records_by_slug[node.slug] = result.page

        await asyncio.gather(
            *(
                generate_leaf(node)
                for node in nodes
                if node.slug in dirty_slugs and not node.has_children
            )
        )

        parent_nodes = sorted(
            (
                node
                for node in nodes
                if node.slug in dirty_slugs and node.has_children
            ),
            key=lambda node: (-node.depth, node.order),
        )
        for node in parent_nodes:
            result = await self.generate_page(
                repo_id,
                node.item,
                language_code=language_code,
                parent_slug=node.parent_slug,
                child_pages=_child_page_records_for_item(node.item, page_records_by_slug),
            )
            results_by_slug[node.slug] = result
            page_records_by_slug[node.slug] = result.page

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
            if node.slug not in dirty_slugs and node.slug in existing_by_slug
        ]
        return WikiUpdateResult(
            repo_id=repo_id,
            language_code=language_code,
            results=[results_by_slug[slug] for slug in generated_slugs],
            reused_pages=reused_pages,
            stale_slugs=stale_slugs,
            missing_slugs=missing_slugs,
            metadata_changed_slugs=metadata_changed_slugs,
            generated_slugs=generated_slugs,
            deleted_page_count=deleted_page_count,
        )

    async def _update_translated_pages(
        self,
        repo_id: str,
        *,
        source_language: str,
        target_language: str,
    ) -> WikiUpdateResult:
        base_update = await self._update_pages_for_language(repo_id, language_code=source_language)
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
        target_dirty_slugs = _translated_dirty_slugs(
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
            PageGenerationResult(page=page, validation_errors=[])
            for page in translated_pages
        ]
        reused_pages = [
            existing_target_by_slug[slug]
            for slug in source_slugs
            if slug not in set(target_dirty_slugs) and slug in existing_target_by_slug
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

    async def _regenerate_page_for_language(
        self,
        repo_id: str,
        slug: str,
        *,
        language_code: str,
    ) -> PageGenerationResult:
        catalog = self.store.get_latest_doc_catalog(repo_id, language_code=language_code)
        if catalog is None:
            raise ValueError("Generate a catalog before regenerating pages.")
        for item, parent_slug in _catalog_items_for_generation(catalog.structure.get("items", [])):
            if _slugify(str(item.get("slug") or item.get("path") or item.get("title") or "")) == slug:
                child_pages = []
                if _has_children(item):
                    child_results = await self._generate_descendant_pages(
                        repo_id,
                        item,
                        language_code=language_code,
                    )
                    child_pages = _child_pages_for_item(
                        item,
                        {result.page.slug: result for result in child_results},
                    )
                return await self.generate_page(
                    repo_id,
                    item,
                    language_code=language_code,
                    parent_slug=parent_slug,
                    child_pages=child_pages,
                )
        raise ValueError(f"Catalog page not found: {slug}")

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

    async def _ensure_base_catalog(self, repo_id: str) -> DocCatalogRecord:
        base_language = self._base_language()
        catalog = self.store.get_latest_doc_catalog(repo_id, language_code=base_language)
        if catalog is not None:
            return catalog
        return await self.catalog_generator.generate_catalog(repo_id, language_code=base_language)

    async def _ensure_base_pages(self, repo_id: str) -> list[PageGenerationResult]:
        base_language = self._base_language()
        await self._ensure_base_catalog(repo_id)
        pages = self.store.list_doc_pages(repo_id, language_code=base_language)
        if pages:
            return [PageGenerationResult(page=page, validation_errors=[]) for page in pages]
        return await self._generate_all_pages_for_language(repo_id, language_code=base_language)

    async def _translate_configured_languages(self, repo_id: str) -> None:
        base_language = self._base_language()
        for language_code in self._translation_languages():
            if language_code == base_language:
                continue
            await self.translate_wiki(
                repo_id,
                source_language=base_language,
                target_language=language_code,
            )

    async def _translate_configured_languages_for_slugs(
        self,
        repo_id: str,
        slugs: list[str],
    ) -> None:
        if not slugs:
            return
        base_language = self._base_language()
        for language_code in self._translation_languages():
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

    def _base_language(self) -> str:
        return _normalize_language(self.settings.wiki_base_language)

    def _translation_languages(self) -> list[str]:
        raw_languages = self.settings.wiki_translation_languages or ""
        languages: list[str] = []
        for raw_language in raw_languages.split(","):
            language_code = _normalize_language(raw_language)
            if raw_language.strip() and language_code not in languages:
                languages.append(language_code)
        return languages

    async def _generate_descendant_pages(
        self,
        repo_id: str,
        item: dict[str, Any],
        *,
        language_code: str = "en",
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
                    language_code=language_code,
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
                language_code=language_code,
                parent_slug=node.parent_slug,
                child_pages=_child_pages_for_item(node.item, results_by_slug),
            )

        for node in nodes:
            if node.slug in results_by_slug:
                results.append(results_by_slug[node.slug])
        return results


__all__ = ["PageGenerationResult", "WikiGenerator", "WikiTranslationResult", "WikiUpdateResult"]


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


def _child_page_records_for_item(
    item: dict[str, Any],
    pages_by_slug: dict[str, DocPageRecord],
) -> list[DocPageRecord]:
    pages: list[DocPageRecord] = []
    for child in _item_children(item):
        page = pages_by_slug.get(_catalog_slug(child))
        if page is not None:
            pages.append(page)
    return pages


def _dirty_wiki_page_slugs(
    nodes: list[_GenerationNode],
    existing_by_slug: dict[str, DocPageRecord],
) -> tuple[set[str], list[str], list[str], list[str]]:
    dirty_slugs: set[str] = set()
    stale_slugs: list[str] = []
    missing_slugs: list[str] = []
    metadata_changed_slugs: list[str] = []
    parent_by_slug = {node.slug: node.parent_slug for node in nodes}

    for node in nodes:
        existing = existing_by_slug.get(node.slug)
        if existing is None:
            missing_slugs.append(node.slug)
            dirty_slugs.add(node.slug)
            continue
        if existing.status != "generated":
            stale_slugs.append(node.slug)
            dirty_slugs.add(node.slug)
            continue
        expected_title = str(node.item.get("title") or "")
        if existing.parent_slug != node.parent_slug or (expected_title and existing.title != expected_title):
            metadata_changed_slugs.append(node.slug)
            dirty_slugs.add(node.slug)

    for slug in [*missing_slugs, *stale_slugs, *metadata_changed_slugs]:
        parent_slug = parent_by_slug.get(slug)
        while parent_slug:
            dirty_slugs.add(parent_slug)
            parent_slug = parent_by_slug.get(parent_slug)

    return (
        dirty_slugs,
        _ordered_unique(stale_slugs),
        _ordered_unique(missing_slugs),
        _ordered_unique(metadata_changed_slugs),
    )


def _translated_dirty_slugs(
    *,
    source_slugs: list[str],
    existing_target_by_slug: dict[str, DocPageRecord],
    base_generated_slugs: list[str],
) -> list[str]:
    dirty_slugs: list[str] = []
    base_generated = set(base_generated_slugs)
    for slug in source_slugs:
        target_page = existing_target_by_slug.get(slug)
        if target_page is None or target_page.status != "generated" or slug in base_generated:
            dirty_slugs.append(slug)
    return _ordered_unique(dirty_slugs)


def _ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return unique


def _has_children(item: dict[str, Any]) -> bool:
    return bool(_item_children(item))


def _item_children(item: dict[str, Any]) -> list[dict[str, Any]]:
    children = item.get("children") or []
    if not isinstance(children, list):
        return []
    return [child for child in children if isinstance(child, dict)]


def _catalog_slug(item: dict[str, Any]) -> str:
    return _slugify(str(item.get("slug") or item.get("path") or item.get("title") or ""))


def _normalize_language(language_code: str | None) -> str:
    return (language_code or "en").strip().lower() or "en"
