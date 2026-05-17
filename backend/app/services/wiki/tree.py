from dataclasses import dataclass
from typing import Any, Protocol

from backend.app.database import DocPageRecord
from backend.app.services.wiki.utils import slugify


@dataclass(frozen=True)
class GenerationNode:
    item: dict[str, Any]
    parent_slug: str | None
    slug: str
    depth: int
    order: int
    has_children: bool


class _PageResultLike(Protocol):
    page: DocPageRecord


def generation_nodes(
    items: list[Any],
    *,
    parent_slug: str | None = None,
    depth: int = 0,
) -> list[GenerationNode]:
    nodes: list[GenerationNode] = []

    def visit(raw_items: list[Any], current_parent_slug: str | None, current_depth: int) -> None:
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            slug = catalog_slug(item)
            children = item_children(item)
            has_children = bool(children)
            kind = str(item.get("kind") or "").lower()
            if kind in {"page", "category"} or not has_children:
                nodes.append(
                    GenerationNode(
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


def child_pages_for_item(
    item: dict[str, Any],
    results_by_slug: dict[str, _PageResultLike],
) -> list[DocPageRecord]:
    pages: list[DocPageRecord] = []
    for child in item_children(item):
        result = results_by_slug.get(catalog_slug(child))
        if result is not None:
            pages.append(result.page)
    return pages


def child_page_records_for_item(
    item: dict[str, Any],
    pages_by_slug: dict[str, DocPageRecord],
) -> list[DocPageRecord]:
    pages: list[DocPageRecord] = []
    for child in item_children(item):
        page = pages_by_slug.get(catalog_slug(child))
        if page is not None:
            pages.append(page)
    return pages


def has_children(item: dict[str, Any]) -> bool:
    return bool(item_children(item))


def item_children(item: dict[str, Any]) -> list[dict[str, Any]]:
    children = item.get("children") or []
    if not isinstance(children, list):
        return []
    return [child for child in children if isinstance(child, dict)]


def catalog_slug(item: dict[str, Any]) -> str:
    return slugify(str(item.get("slug") or item.get("path") or item.get("title") or ""))
