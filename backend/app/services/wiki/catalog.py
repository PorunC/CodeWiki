import re
from dataclasses import replace
from typing import Any

from backend.app.database import SQLiteStore
from backend.app.services.graph_rag import RetrievalTrace

MAX_CATALOG_ITEMS = 14
MAX_SOURCE_HINT_CHUNKS = 10
MAX_SOURCE_HINT_CHUNKS_PER_FILE = 3

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
            for raw_item in raw_items[:MAX_CATALOG_ITEMS]
        )
        if item is not None
    ]
    if not items:
        items = [
            {
                "title": "Overview",
                "slug": "overview",
                "path": "overview",
                "order": 0,
                "kind": "page",
                "topic": "repository overview",
                "children": [],
            }
        ]
    items = _sort_catalog_items(items)
    return title, items


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


def _source_hints_from_item(item: dict[str, Any]) -> list[str]:
    hints = item.get("source_hints")
    if not isinstance(hints, list):
        return []
    return [
        hint.strip().strip("/")
        for hint in (str(value) for value in hints)
        if hint.strip().strip("/")
    ][:8]


def _trace_with_source_hint_chunks(
    trace: RetrievalTrace,
    store: SQLiteStore,
    repo_id: str,
    source_hints: list[str],
) -> RetrievalTrace:
    if not source_hints:
        return trace

    hinted_chunks: list[dict[str, object]] = []
    per_file_counts: dict[str, int] = {}
    for chunk in store.list_code_chunks(repo_id):
        if not _matches_source_hint(chunk.file_path, source_hints):
            continue
        if per_file_counts.get(chunk.file_path, 0) >= MAX_SOURCE_HINT_CHUNKS_PER_FILE:
            continue
        per_file_counts[chunk.file_path] = per_file_counts.get(chunk.file_path, 0) + 1
        hinted_chunks.append(
            {
                "id": chunk.id,
                "node_id": chunk.node_id,
                "file_path": chunk.file_path,
                "start_line": chunk.start_line,
                "end_line": chunk.end_line,
                "content": chunk.content,
                "content_hash": chunk.content_hash,
                "token_count": chunk.token_count,
                "score": 0.45,
                "reasons": ["source_hint"],
            }
        )
        if len(hinted_chunks) >= MAX_SOURCE_HINT_CHUNKS:
            break

    if not hinted_chunks:
        return trace
    return replace(
        trace,
        source_chunks=_dedupe_source_chunks([*trace.source_chunks, *hinted_chunks]),
    )


def _matches_source_hint(file_path: str, source_hints: list[str]) -> bool:
    normalized = file_path.strip("/")
    return any(normalized == hint or normalized.startswith(f"{hint.rstrip('/')}/") for hint in source_hints)


def _dedupe_source_chunks(chunks: list[dict[str, object]]) -> list[dict[str, object]]:
    seen: set[str] = set()
    deduped: list[dict[str, object]] = []
    for chunk in chunks:
        chunk_id = str(chunk.get("id") or "")
        key = chunk_id or (
            f"{chunk.get('file_path')}:{chunk.get('start_line')}:{chunk.get('end_line')}"
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(chunk)
    return deduped


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
