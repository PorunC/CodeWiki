import uuid
from dataclasses import dataclass
from typing import Any

from backend.app.database import DocCatalogRecord, DocPageRecord, SQLiteStore
from backend.app.services.llm_gateway import LLMGateway
from backend.app.services.llm_operations import CachedLLMService, LLMOperation
from backend.app.services.wiki.catalog import _validate_catalog_payload
from backend.app.services.wiki.language import normalize_language as _normalize_language
from backend.app.services.wiki.prompts import _json_object, _load_prompt
from backend.app.services.wiki.utils import ordered_unique as _ordered_unique

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

    async def translate_wiki(
        self,
        repo_id: str,
        *,
        source_language: str,
        target_language: str,
    ) -> WikiTranslationResult:
        source_language = _normalize_language(source_language)
        target_language = _normalize_language(target_language)
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
        source_language = _normalize_language(source_language)
        target_language = _normalize_language(target_language)
        source_catalog = self.store.get_latest_doc_catalog(repo_id, language_code=source_language)
        if source_catalog is None:
            raise ValueError(f"Source catalog not found for language: {source_language}")
        catalog = self.store.get_latest_doc_catalog(repo_id, language_code=target_language)
        if catalog is not None:
            target_paths = _catalog_paths(catalog.structure.get("items", []))
            source_paths = _catalog_paths(source_catalog.structure.get("items", []))
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
        source_language = _normalize_language(source_language)
        target_language = _normalize_language(target_language)
        requested_slugs = _ordered_unique(slugs)
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
        title_entries = _catalog_title_entries(catalog.structure.get("items", []))
        payload = {
            "content_type": "catalog",
            "source_language": source_language,
            "target_language": target_language,
            "title": catalog.title,
            "items": title_entries,
            "style_guide": _translation_style_guide(target_language),
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
            "items": _apply_catalog_title_translations(
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
            "style_guide": _translation_style_guide(target_language),
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
                    messages=_translation_messages(attempt_payload, validation_errors),
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
                _validate_translation_response(response, content_type=content_type)
                return response
            except ValueError as exc:
                validation_errors = [str(exc)]
                self.store.update_llm_run_status(
                    completion.run.id,
                    status="error",
                    error=str(exc),
                )
                attempt_payload = _translation_repair_payload(
                    payload,
                    completion.result.content,
                    validation_errors,
                )

        raise ValueError(
            f"Translation LLM did not return a valid {content_type} JSON object "
            "after repair attempts: "
            + "; ".join(validation_errors)
        )


def _translation_messages(
    payload: dict[str, Any],
    validation_errors: list[str] | None = None,
) -> list[dict[str, str]]:
    prompt = _load_prompt("translation.md")
    instruction = (
        "Return only one valid JSON object for the requested translation shape. "
        "Do not include Markdown fences, comments, trailing commas, or prose outside JSON."
    )
    if validation_errors:
        instruction = (
            f"{instruction}\nRepair the previous response. Validation errors: "
            f"{validation_errors}"
        )
    return [
        {"role": "system", "content": prompt},
        {"role": "user", "content": f"{instruction}\n{_json_dumps(payload)}"},
    ]


def _translation_repair_payload(
    payload: dict[str, Any],
    previous_response: str,
    validation_errors: list[str],
) -> dict[str, Any]:
    content_type = str(payload.get("content_type") or "translation")
    shape = "title and items" if content_type == "catalog" else "title and markdown"
    return {
        **payload,
        "previous_response": previous_response[:6000],
        "validation_errors": validation_errors,
        "repair_instructions": (
            f"Repair the {content_type} translation. Return one valid JSON object only, "
            f"with {shape}. Preserve code identifiers, paths, URLs, slugs, anchors, "
            "and source links exactly as instructed."
        ),
    }


def _validate_translation_response(response: dict[str, Any], *, content_type: str) -> None:
    title = response.get("title")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("Translation JSON must include a non-empty title.")
    if content_type == "catalog":
        items = response.get("items")
        if not isinstance(items, list):
            raise ValueError("Catalog translation JSON must include an items array.")
    elif content_type == "page":
        markdown = response.get("markdown")
        if not isinstance(markdown, str) or not markdown.strip():
            raise ValueError("Page translation JSON must include non-empty markdown.")
    else:
        raise ValueError(f"Unsupported translation content_type: {content_type}")


def _translation_style_guide(target_language: str) -> dict[str, object]:
    language = _normalize_language(target_language)
    if language in {"zh", "zh-cn", "zh-hans", "cn"} or language.startswith("zh-"):
        return {
            "locale": "zh-Hans",
            "voice": "natural Chinese technical documentation for developers in China",
            "goals": [
                "Use fluent Simplified Chinese rather than word-for-word translation.",
                "Prefer concise headings and direct explanations.",
                "Keep Chinese sentence order natural; split long English sentences when needed.",
                "Use conventional Chinese technical terms while preserving common English terms.",
            ],
            "avoid": [
                "machine-translation tone",
                "overusing 该, 此, 其, 进行, 通过...来, 被用于, 负责于",
                "stiff passive voice",
                "long 的 chains",
                "English-style modifier order",
            ],
            "preferred_terms": {
                "Overview": "概览",
                "Architecture": "架构",
                "Reading Guide": "阅读指南",
                "Dependencies": "依赖关系",
                "Relevant source files": "相关源文件",
                "Sources": "来源",
                "Control Flow": "控制流程",
                "Data Model": "数据模型",
                "Failure Handling": "故障处理",
                "Configuration": "配置",
                "Operations": "运维",
                "Testing": "测试",
            },
        }
    return {
        "locale": language,
        "voice": "natural target-language technical documentation",
        "goals": [
            "Localize prose instead of translating word-for-word.",
            "Keep headings concise and idiomatic.",
            "Preserve all technical identifiers and links exactly.",
        ],
    }


def _catalog_title_entries(items: list[Any]) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []

    def visit(raw_items: list[Any]) -> None:
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            path = str(item.get("path") or item.get("slug") or item.get("title") or "")
            entries.append({"path": path, "title": str(item.get("title") or path)})
            children = item.get("children") or []
            if isinstance(children, list):
                visit(children)

    visit(items)
    return entries


def _catalog_paths(items: list[Any]) -> list[str]:
    paths: list[str] = []

    def visit(raw_items: list[Any]) -> None:
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            paths.append(str(item.get("path") or item.get("slug") or item.get("title") or ""))
            children = item.get("children") or []
            if isinstance(children, list):
                visit(children)

    visit(items)
    return paths


def _apply_catalog_title_translations(
    original_items: list[Any],
    translated_items: Any,
) -> list[dict[str, Any]]:
    translated_by_path = {
        str(item.get("path")): str(item.get("title"))
        for item in translated_items or []
        if isinstance(item, dict) and item.get("path") and item.get("title")
    }

    def copy_item(item: dict[str, Any]) -> dict[str, Any]:
        path = str(item.get("path") or item.get("slug") or item.get("title") or "")
        copied = dict(item)
        copied["title"] = translated_by_path.get(path, str(item.get("title") or path))
        children = item.get("children") or []
        copied["children"] = [
            copy_item(child)
            for child in children
            if isinstance(child, dict)
        ] if isinstance(children, list) else []
        return copied

    return [
        copy_item(item)
        for item in original_items
        if isinstance(item, dict)
    ]


def _json_dumps(payload: dict[str, Any]) -> str:
    import json

    return json.dumps(payload, ensure_ascii=False)
