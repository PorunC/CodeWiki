import asyncio
import uuid
from dataclasses import dataclass
from typing import Any

from backend.app.database import DocCatalogRecord, DocPageRecord, CodeWikiStore
from backend.app.services.llm.gateway import LLMGateway
from backend.app.services.llm.run_recorder import LLMCallError
from backend.app.services.llm.operations import CachedLLMService, LLMOperation
from backend.app.services.wiki.catalog import _validate_catalog_payload
from backend.app.services.wiki.incremental_strategy import WikiIncrementalStrategy
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
TRANSLATION_CONCURRENCY = 3
TRANSLATION_PROMPT_VERSION = "translation:wiki:v3"
TRANSLATION_MARKDOWN_CHUNK_CHARS = 8000


@dataclass(frozen=True)
class WikiTranslationResult:
    catalog: DocCatalogRecord
    pages: list[DocPageRecord]
    source_language: str
    target_language: str


class WikiTranslator:
    def __init__(
        self,
        llm: LLMGateway,
        *,
        store: CodeWikiStore,
        incremental_strategy: WikiIncrementalStrategy | None = None,
        concurrency: int = TRANSLATION_CONCURRENCY,
    ) -> None:
        self.llm = llm
        self.store = store
        self.incremental_strategy = incremental_strategy or WikiIncrementalStrategy()
        self.concurrency = max(1, concurrency)
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
        source_pages = self.store.list_doc_pages(repo_id, language_code=source_language)
        existing_target_by_slug = {
            page.slug: page
            for page in self.store.list_doc_pages(repo_id, language_code=target_language)
        }
        source_updated_slugs = _source_updated_slugs(source_pages, existing_target_by_slug)
        dirty_slugs = self.incremental_strategy.translated_dirty_slugs(
            source_slugs=[page.slug for page in source_pages],
            existing_target_by_slug=existing_target_by_slug,
            base_generated_slugs=source_updated_slugs,
        )
        dirty_slug_set = set(dirty_slugs)
        translated_dirty_pages = await self._translate_pages(
            [page for page in source_pages if page.slug in dirty_slug_set],
            source_language=source_language,
            target_language=target_language,
        )
        translated_dirty_by_slug = {page.slug: page for page in translated_dirty_pages}
        pages = [
            translated_dirty_by_slug.get(page.slug) or existing_target_by_slug[page.slug]
            for page in source_pages
            if page.slug in translated_dirty_by_slug or page.slug in existing_target_by_slug
        ]
        return WikiTranslationResult(
            catalog=translated_catalog,
            pages=pages,
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
        return await self._translate_pages(
            [
                source_pages_by_slug[slug]
                for slug in requested_slugs
                if slug in source_pages_by_slug
            ],
            source_language=source_language,
            target_language=target_language,
        )

    async def _translate_pages(
        self,
        pages: list[DocPageRecord],
        *,
        source_language: str,
        target_language: str,
    ) -> list[DocPageRecord]:
        if not pages:
            return []
        semaphore = asyncio.Semaphore(self.concurrency)

        async def translate_one(page: DocPageRecord) -> DocPageRecord:
            async with semaphore:
                return await self._translate_page(
                    page,
                    source_language=source_language,
                    target_language=target_language,
                )

        first = await translate_one(pages[0])
        rest = await asyncio.gather(*(translate_one(page) for page in pages[1:]))
        return [first, *rest]

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
        try:
            response = await self._translate_page_response(
                page,
                source_language=source_language,
                target_language=target_language,
            )
        except (LLMCallError, ValueError) as exc:
            return self._save_translation_draft(
                page,
                target_language=target_language,
                error=str(exc),
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

    async def _translate_page_response(
        self,
        page: DocPageRecord,
        *,
        source_language: str,
        target_language: str,
    ) -> dict[str, Any]:
        chunks = _markdown_translation_chunks(page.markdown)
        if len(chunks) <= 1:
            return await self._complete_translation_json(
                page.repo_id,
                self._page_translation_payload(
                    page,
                    source_language=source_language,
                    target_language=target_language,
                    markdown=page.markdown,
                ),
                cache_parts=("page", page.id, source_language, target_language),
                content_type="page",
            )

        translated_chunks: list[str] = []
        translated_title = page.title
        for index, chunk in enumerate(chunks):
            response = await self._complete_translation_json(
                page.repo_id,
                self._page_translation_payload(
                    page,
                    source_language=source_language,
                    target_language=target_language,
                    markdown=chunk,
                    chunk_index=index + 1,
                    chunk_count=len(chunks),
                ),
                cache_parts=(
                    "page",
                    page.id,
                    source_language,
                    target_language,
                    "chunk",
                    index + 1,
                    len(chunks),
                ),
                content_type="page",
            )
            if index == 0:
                translated_title = str(response.get("title") or translated_title)
            translated_chunks.append(str(response.get("markdown") or chunk))

        return {
            "title": translated_title,
            "markdown": "\n\n".join(chunk.strip() for chunk in translated_chunks if chunk.strip()),
        }

    def _page_translation_payload(
        self,
        page: DocPageRecord,
        *,
        source_language: str,
        target_language: str,
        markdown: str,
        chunk_index: int | None = None,
        chunk_count: int | None = None,
    ) -> dict[str, Any]:
        rules = [
            "Translate prose and headings to the target language with natural local writing.",
            "For Chinese targets, rewrite awkward literal phrasing into fluent Chinese technical prose.",
            "Keep code blocks, inline code, file paths, URLs, anchors, and identifiers unchanged.",
            "Keep Markdown structure and links valid.",
            "Do not remove source citations or source sections.",
            "Return JSON with title and markdown.",
        ]
        payload: dict[str, Any] = {
            "content_type": "page",
            "source_language": source_language,
            "target_language": target_language,
            "title": page.title,
            "markdown": markdown,
            "source_refs": page.source_refs,
            "style_guide": self.style_guide.for_language(target_language),
            "rules": rules,
        }
        if chunk_index is not None and chunk_count is not None:
            payload["translation_chunk"] = {
                "index": chunk_index,
                "count": chunk_count,
                "scope": (
                    "Translate only this Markdown chunk. Return the translated chunk as markdown; "
                    "do not summarize missing chunks or add cross-chunk framing."
                ),
            }
            payload["rules"] = [
                *rules,
                "This is one chunk of a longer page; preserve local Markdown structure only for this chunk.",
                "Do not add an extra page title unless the chunk already contains that heading.",
            ]
        return payload

    def _save_translation_draft(
        self,
        page: DocPageRecord,
        *,
        target_language: str,
        error: str,
    ) -> DocPageRecord:
        draft = DocPageRecord(
            id=uuid.uuid4().hex,
            repo_id=page.repo_id,
            language_code=target_language,
            slug=page.slug,
            title=page.title,
            parent_slug=page.parent_slug,
            markdown=_translation_draft_markdown(page, error),
            source_refs=page.source_refs,
            graph_refs=page.graph_refs,
            status="draft",
            updated_at=None,
        )
        return self.store.upsert_doc_page(draft)

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


def _markdown_translation_chunks(
    markdown: str,
    *,
    max_chars: int = TRANSLATION_MARKDOWN_CHUNK_CHARS,
) -> list[str]:
    if len(markdown) <= max_chars:
        return [markdown]
    blocks = _markdown_blocks(markdown)
    chunks: list[str] = []
    current = ""
    for block in blocks:
        if not block:
            continue
        if len(block) > max_chars:
            if current.strip():
                chunks.append(current.strip())
                current = ""
            chunks.extend(_split_large_markdown_block(block, max_chars=max_chars))
            continue
        separator = "\n\n" if current and not current.endswith("\n\n") else ""
        candidate = f"{current}{separator}{block}" if current else block
        if len(candidate) > max_chars and current.strip():
            chunks.append(current.strip())
            current = block
        else:
            current = candidate
    if current.strip():
        chunks.append(current.strip())
    return chunks or [markdown]


def _markdown_blocks(markdown: str) -> list[str]:
    lines = markdown.splitlines()
    blocks: list[str] = []
    current: list[str] = []
    in_fence = False

    def flush() -> None:
        if current:
            blocks.append("\n".join(current).strip())
            current.clear()

    for line in lines:
        stripped = line.lstrip()
        is_fence = stripped.startswith("```")
        is_heading = stripped.startswith("#") and not in_fence
        if is_heading:
            flush()
        current.append(line)
        if is_fence:
            in_fence = not in_fence
    flush()
    return blocks


def _split_large_markdown_block(block: str, *, max_chars: int) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    current_size = 0
    in_fence = False
    for line in block.splitlines():
        line_size = len(line) + 1
        if current and not in_fence and current_size + line_size > max_chars:
            chunks.append("\n".join(current).strip())
            current = []
            current_size = 0
        current.append(line)
        current_size += line_size
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
    if current:
        chunks.append("\n".join(current).strip())
    return [chunk for chunk in chunks if chunk]


def _source_updated_slugs(
    source_pages: list[DocPageRecord],
    existing_target_by_slug: dict[str, DocPageRecord],
) -> list[str]:
    updated_slugs: list[str] = []
    for source_page in source_pages:
        target_page = existing_target_by_slug.get(source_page.slug)
        if target_page is None:
            continue
        if (
            source_page.updated_at
            and target_page.updated_at
            and source_page.updated_at > target_page.updated_at
        ):
            updated_slugs.append(source_page.slug)
    return updated_slugs


def _translation_draft_markdown(page: DocPageRecord, error: str) -> str:
    safe_error = error.replace("\x00", "").strip()
    if len(safe_error) > 1200:
        safe_error = f"{safe_error[:1200]}..."
    return "\n\n".join(
        [
            f"# {page.title}",
            (
                "> Translation failed after repair attempts. This draft keeps the source "
                "content so wiki generation can continue."
            ),
            f"> Error: {safe_error}" if safe_error else "> Error: translation failed.",
            page.markdown,
        ]
    )
