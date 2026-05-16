import re
from typing import Any

from backend.app.services.wiki.catalog.source_hints import (
    _dedupe_source_chunks,
    _matches_source_hint,
    _source_hints_from_item,
    _trace_with_source_hint_chunks,
)

MAX_CATALOG_ITEMS = 18
MAX_LLM_CATALOG_ITEMS = 14

SPECIAL_CATALOG_PAGES: tuple[dict[str, Any], ...] = (
    {
        "title": "Overview",
        "slug": "overview",
        "path": "overview",
        "order": 0,
        "kind": "page",
        "topic": "repository overview, entry points, README, and main developer orientation",
        "source_hints": ["README.md"],
        "children": [],
    },
    {
        "title": "Architecture",
        "slug": "architecture",
        "path": "architecture",
        "order": 1,
        "kind": "page",
        "topic": "repository architecture, runtime layers, core components, and cross-module flows",
        "source_hints": [],
        "children": [],
    },
    {
        "title": "Reading Guide",
        "slug": "reading-guide",
        "path": "reading-guide",
        "order": 2,
        "kind": "page",
        "topic": "recommended reading order for understanding the repository from entry points to internals",
        "source_hints": ["README.md"],
        "children": [],
    },
    {
        "title": "Dependencies",
        "slug": "dependencies",
        "path": "dependencies",
        "order": 3,
        "kind": "page",
        "topic": "internal dependencies, external packages, imports, configuration, and integration boundaries",
        "source_hints": [],
        "children": [],
    },
)


def _normalize_catalog_payload(payload: dict[str, Any], repo_name: str) -> tuple[str, list[dict[str, Any]]]:
    root = payload.get("catalog") if isinstance(payload.get("catalog"), dict) else payload
    title = str(root.get("title") or f"{repo_name} Wiki")
    raw_items = root.get("items") or root.get("pages") or []
    if not isinstance(raw_items, list):
        raise ValueError("Catalog response must contain an items array.")
    used_slugs: set[str] = set()
    items = [
        item
        for item in (
            _normalize_catalog_item(raw_item, used_slugs)
            for raw_item in raw_items[:MAX_LLM_CATALOG_ITEMS]
        )
        if item is not None
    ]
    if not items:
        items = []
    items = _ensure_special_catalog_pages(items)
    items = _sort_catalog_items(items)
    return title, items[:MAX_CATALOG_ITEMS]


def _validate_catalog_payload(payload: dict[str, Any]) -> None:
    root = payload.get("catalog") if isinstance(payload.get("catalog"), dict) else payload
    raw_items = root.get("items") or root.get("pages")
    if not isinstance(raw_items, list):
        raise ValueError("Catalog response must contain an items array.")


def _normalize_catalog_item(raw_item: Any, used_slugs: set[str]) -> dict[str, Any] | None:
    if not isinstance(raw_item, dict):
        return None
    title = str(raw_item.get("title") or "").strip()
    if not title:
        return None
    slug = _unique_slug(_slugify(str(raw_item.get("slug") or raw_item.get("path") or title)), used_slugs)
    path = str(raw_item.get("path") or slug).strip().strip("/") or slug
    topic = str(raw_item.get("topic") or title)
    raw_kind = str(raw_item.get("kind") or "").strip().lower()
    kind = raw_kind if raw_kind in {"page", "category"} else "page"
    raw_order = raw_item.get("order")
    order = raw_order if isinstance(raw_order, int) and raw_order >= 0 else len(used_slugs) - 1
    source_hints = raw_item.get("source_hints") if isinstance(raw_item.get("source_hints"), list) else []
    raw_children = raw_item.get("children") or []
    children = []
    if isinstance(raw_children, list):
        children = [
            child
            for child in (_normalize_catalog_item(child, used_slugs) for child in raw_children[:8])
            if child is not None
        ]
    return {
        "title": title,
        "slug": slug,
        "path": path,
        "order": order,
        "kind": kind,
        "topic": topic,
        "source_hints": [str(hint) for hint in source_hints[:8]],
        "children": children,
    }


def _sort_catalog_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for item in items:
        children = item.get("children")
        if isinstance(children, list):
            item["children"] = _sort_catalog_items(children)
    return sorted(items, key=lambda item: (int(item.get("order") or 0), str(item.get("title") or "")))


def _ensure_special_catalog_pages(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    existing_slugs = {_catalog_slug(item) for item in _flatten_catalog_item_dicts(items)}
    next_items = list(items)
    for special in SPECIAL_CATALOG_PAGES:
        if str(special["slug"]) in existing_slugs:
            continue
        next_items.append({**special, "children": []})
        existing_slugs.add(str(special["slug"]))
    for item in next_items:
        item["order"] = _special_order(str(item.get("slug") or ""), int(item.get("order") or 0))
    return next_items


def _flatten_catalog_item_dicts(items: list[Any]) -> list[dict[str, Any]]:
    flat: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        flat.append(item)
        children = item.get("children") or []
        if isinstance(children, list):
            flat.extend(_flatten_catalog_item_dicts(children))
    return flat


def _special_order(slug: str, current_order: int) -> int:
    for special in SPECIAL_CATALOG_PAGES:
        if str(special["slug"]) == slug:
            return int(special["order"])
    return current_order + len(SPECIAL_CATALOG_PAGES)


def _catalog_context_for_page(
    items: list[Any],
    *,
    slug: str,
    parent_slug: str | None,
) -> dict[str, Any]:
    summaries = _catalog_item_summaries(items)
    current = next((item for item in summaries if item["slug"] == slug), None)
    parent = next((item for item in summaries if item["slug"] == parent_slug), None) if parent_slug else None
    related_pages = _related_catalog_pages(summaries, slug=slug, parent_slug=parent_slug)
    return {
        "current": current
        or {
            "title": "",
            "slug": slug,
            "path": slug,
            "kind": "page",
            "parent_slug": parent_slug,
            "depth": 0,
        },
        "parent": parent,
        "related_pages": related_pages,
        "page_count": sum(1 for item in summaries if item["kind"] == "page"),
    }


def _catalog_item_summaries(
    items: list[Any],
    *,
    parent_slug: str | None = None,
    depth: int = 0,
) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for raw_item in items:
        if not isinstance(raw_item, dict):
            continue
        slug = _catalog_slug(raw_item)
        summary = {
            "title": str(raw_item.get("title") or ""),
            "slug": slug,
            "path": str(raw_item.get("path") or slug),
            "kind": str(raw_item.get("kind") or "page").lower(),
            "topic": str(raw_item.get("topic") or raw_item.get("title") or ""),
            "parent_slug": parent_slug,
            "order": int(raw_item.get("order") or 0),
            "depth": depth,
            "source_hints": _source_hints_from_item(raw_item)[:4],
        }
        summaries.append(summary)
        children = raw_item.get("children") or []
        if isinstance(children, list):
            summaries.extend(
                _catalog_item_summaries(children, parent_slug=slug, depth=depth + 1)
            )
    return summaries[:48]


def _related_catalog_pages(
    summaries: list[dict[str, Any]],
    *,
    slug: str,
    parent_slug: str | None,
) -> list[dict[str, Any]]:
    page_summaries = [
        item
        for item in summaries
        if item["kind"] == "page" and item["slug"] != slug
    ]
    ranked = sorted(
        page_summaries,
        key=lambda item: (
            0 if item["parent_slug"] == parent_slug else 1,
            item["depth"],
            item["order"],
            item["title"],
        ),
    )
    return ranked[:12]


def _flatten_catalog_items(
    items: list[Any],
    *,
    parent_slug: str | None = None,
):
    for item in items:
        if not isinstance(item, dict):
            continue
        yield item, parent_slug
        slug = _catalog_slug(item)
        children = item.get("children") or []
        if isinstance(children, list):
            yield from _flatten_catalog_items(children, parent_slug=slug)


def _catalog_items_for_generation(
    items: list[Any],
    *,
    parent_slug: str | None = None,
):
    for item in items:
        if not isinstance(item, dict):
            continue
        children = item.get("children") or []
        has_children = isinstance(children, list) and bool(children)
        kind = str(item.get("kind") or "").lower()
        if kind in {"page", "category"} or not has_children:
            yield item, parent_slug
        if isinstance(children, list):
            yield from _catalog_items_for_generation(children, parent_slug=_catalog_slug(item))


def _catalog_slug(item: dict[str, Any]) -> str:
    return _slugify(str(item.get("slug") or item.get("path") or item.get("title") or ""))


def _source_chunk_summaries(chunks: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        {
            "id": chunk.get("id"),
            "node_id": chunk.get("node_id"),
            "file_path": chunk.get("file_path"),
            "start_line": chunk.get("start_line"),
            "end_line": chunk.get("end_line"),
            "reasons": chunk.get("reasons"),
        }
        for chunk in chunks
    ]


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    return slug or "page"


def _unique_slug(slug: str, used_slugs: set[str]) -> str:
    candidate = slug
    index = 2
    while candidate in used_slugs:
        candidate = f"{slug}-{index}"
        index += 1
    used_slugs.add(candidate)
    return candidate


__all__ = [
    "MAX_CATALOG_ITEMS",
    "SPECIAL_CATALOG_PAGES",
    "_catalog_context_for_page",
    "_catalog_item_summaries",
    "_catalog_items_for_generation",
    "_catalog_slug",
    "_dedupe_source_chunks",
    "_flatten_catalog_items",
    "_ensure_special_catalog_pages",
    "_matches_source_hint",
    "_normalize_catalog_payload",
    "_related_catalog_pages",
    "_slugify",
    "_source_chunk_summaries",
    "_source_hints_from_item",
    "_sort_catalog_items",
    "_trace_with_source_hint_chunks",
    "_unique_slug",
    "_validate_catalog_payload",
]
