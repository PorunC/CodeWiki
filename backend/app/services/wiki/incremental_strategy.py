from dataclasses import dataclass

from backend.app.database import DocPageRecord
from backend.app.services.wiki.page_generator import PageGenerationResult
from backend.app.services.wiki.tree import GenerationNode
from backend.app.services.wiki.utils import ordered_unique


@dataclass(frozen=True)
class DirtyPagePlan:
    dirty_slugs: set[str]
    stale_slugs: list[str]
    missing_slugs: list[str]
    metadata_changed_slugs: list[str]


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


class WikiIncrementalStrategy:
    def plan_dirty_pages(
        self,
        nodes: list[GenerationNode],
        existing_by_slug: dict[str, DocPageRecord],
    ) -> DirtyPagePlan:
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
            title_changed = expected_title and existing.title != expected_title
            parent_changed = existing.parent_slug != node.parent_slug
            if parent_changed or title_changed:
                metadata_changed_slugs.append(node.slug)
                dirty_slugs.add(node.slug)

        for slug in [*missing_slugs, *stale_slugs, *metadata_changed_slugs]:
            parent_slug = parent_by_slug.get(slug)
            while parent_slug:
                dirty_slugs.add(parent_slug)
                parent_slug = parent_by_slug.get(parent_slug)

        return DirtyPagePlan(
            dirty_slugs=dirty_slugs,
            stale_slugs=ordered_unique(stale_slugs),
            missing_slugs=ordered_unique(missing_slugs),
            metadata_changed_slugs=ordered_unique(metadata_changed_slugs),
        )

    def translated_dirty_slugs(
        self,
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
        return ordered_unique(dirty_slugs)

