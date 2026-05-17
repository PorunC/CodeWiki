import json
from typing import Any

from backend.app.services.wiki.language import normalize_language
from backend.app.services.wiki.prompts import _load_prompt


class TranslationPromptBuilder:
    def messages(
        self,
        payload: dict[str, Any],
        validation_errors: list[str] | None = None,
    ) -> list[dict[str, str]]:
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
            {"role": "system", "content": _load_prompt("translation.md")},
            {"role": "user", "content": f"{instruction}\n{self._json_dumps(payload)}"},
        ]

    def repair_payload(
        self,
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

    @staticmethod
    def _json_dumps(payload: dict[str, Any]) -> str:
        return json.dumps(payload, ensure_ascii=False)


class TranslationResponseValidator:
    def validate(self, response: dict[str, Any], *, content_type: str) -> None:
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


class TranslationStyleGuide:
    def for_language(self, target_language: str) -> dict[str, object]:
        language = normalize_language(target_language)
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


class CatalogTitleTranslationMapper:
    def title_entries(self, items: list[Any]) -> list[dict[str, str]]:
        entries: list[dict[str, str]] = []
        for item in self._catalog_items(items):
            path = self.item_path(item)
            entries.append({"path": path, "title": str(item.get("title") or path)})
        return entries

    def paths(self, items: list[Any]) -> list[str]:
        return [self.item_path(item) for item in self._catalog_items(items)]

    def apply(
        self,
        original_items: list[Any],
        translated_items: Any,
    ) -> list[dict[str, Any]]:
        translated_by_path = {
            str(item.get("path")): str(item.get("title"))
            for item in translated_items or []
            if isinstance(item, dict) and item.get("path") and item.get("title")
        }
        return [
            self._copy_translated_item(item, translated_by_path)
            for item in original_items
            if isinstance(item, dict)
        ]

    def _copy_translated_item(
        self,
        item: dict[str, Any],
        translated_by_path: dict[str, str],
    ) -> dict[str, Any]:
        path = self.item_path(item)
        copied = dict(item)
        copied["title"] = translated_by_path.get(path, str(item.get("title") or path))
        children = item.get("children") or []
        copied["children"] = [
            self._copy_translated_item(child, translated_by_path)
            for child in children
            if isinstance(child, dict)
        ] if isinstance(children, list) else []
        return copied

    def _catalog_items(self, items: list[Any]) -> list[dict[str, Any]]:
        catalog_items: list[dict[str, Any]] = []

        def visit(raw_items: list[Any]) -> None:
            for item in raw_items:
                if not isinstance(item, dict):
                    continue
                catalog_items.append(item)
                children = item.get("children") or []
                if isinstance(children, list):
                    visit(children)

        visit(items)
        return catalog_items

    @staticmethod
    def item_path(item: dict[str, Any]) -> str:
        return str(item.get("path") or item.get("slug") or item.get("title") or "")
