import uuid
from dataclasses import dataclass
from typing import Any

from backend.app.database import DocCatalogRecord, DocPageRecord, SQLiteStore
from backend.app.services.llm_gateway import LLMGateway
from backend.app.services.llm_run_recorder import complete_with_cache
from backend.app.services.wiki.catalog import _validate_catalog_payload
from backend.app.services.wiki.prompts import _json_object, _load_prompt


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
            "rules": [
                "Translate only human-facing title text.",
                "Do not translate slugs, paths, topics, source_hints, or code identifiers.",
                "Return JSON with title and items containing path and title.",
            ],
        }
        completion = await complete_with_cache(
            self.store,
            catalog.repo_id,
            llm=self.llm,
            task_type="translation",
            messages=_translation_messages(payload),
            input_payload=payload,
            cache_key=f"translation:catalog:{catalog.id}:{source_language}:{target_language}",
            model_alias="translation",
            prompt_version="translation:wiki:v1",
            response_format="json_object",
        )
        response = _json_object(completion.result.content)
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
            "rules": [
                "Translate prose and headings to the target language.",
                "Keep code blocks, inline code, file paths, URLs, anchors, and identifiers unchanged.",
                "Keep Markdown structure and links valid.",
                "Do not remove source citations or source sections.",
                "Return JSON with title and markdown.",
            ],
        }
        completion = await complete_with_cache(
            self.store,
            page.repo_id,
            llm=self.llm,
            task_type="translation",
            messages=_translation_messages(payload),
            input_payload=payload,
            cache_key=f"translation:page:{page.id}:{source_language}:{target_language}",
            model_alias="translation",
            prompt_version="translation:wiki:v1",
            response_format="json_object",
        )
        response = _json_object(completion.result.content)
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


def _translation_messages(payload: dict[str, Any]) -> list[dict[str, str]]:
    prompt = _load_prompt("translation.md")
    return [
        {"role": "system", "content": prompt},
        {"role": "user", "content": _json_dumps(payload)},
    ]


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


def _normalize_language(language_code: str | None) -> str:
    return (language_code or "en").strip().lower() or "en"


def _json_dumps(payload: dict[str, Any]) -> str:
    import json

    return json.dumps(payload, ensure_ascii=False)
