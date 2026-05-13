import type { WikiCatalogItem, WikiPageRecord } from "../api/types";
import { sortCatalogItems } from "./catalog";
import type { RelatedWikiPage } from "./types";

export function relatedPagesForPage(
  items: WikiCatalogItem[],
  pageBySlug: Map<string, WikiPageRecord>,
  slug: string
): RelatedWikiPage[] {
  const summaries = flattenCatalogSummaries(items);
  const current = summaries.find((item) => item.slug === slug);
  if (!current) {
    return [];
  }
  return summaries
    .filter((item) => item.slug !== slug && pageBySlug.has(item.slug))
    .sort((left, right) => {
      const leftScore = relatedPageScore(left, current);
      const rightScore = relatedPageScore(right, current);
      if (leftScore !== rightScore) {
        return leftScore - rightScore;
      }
      if (left.order !== right.order) {
        return left.order - right.order;
      }
      return left.title.localeCompare(right.title);
    })
    .slice(0, 6)
    .map((item) => ({
      slug: item.slug,
      title: item.title,
      path: item.path
    }));
}

function flattenCatalogSummaries(
  items: WikiCatalogItem[],
  parentSlug: string | null = null,
  depth = 0
): Array<RelatedWikiPage & { parentSlug: string | null; depth: number; order: number; kind: string }> {
  const summaries: Array<RelatedWikiPage & { parentSlug: string | null; depth: number; order: number; kind: string }> = [];
  sortCatalogItems(items).forEach((item, index) => {
    summaries.push({
      slug: item.slug,
      title: item.title,
      path: item.path ?? item.slug,
      parentSlug,
      depth,
      order: typeof item.order === "number" ? item.order : index,
      kind: item.kind ?? "page"
    });
    summaries.push(...flattenCatalogSummaries(item.children ?? [], item.slug, depth + 1));
  });
  return summaries;
}

function relatedPageScore(
  candidate: { parentSlug: string | null; depth: number; kind: string },
  current: { parentSlug: string | null; depth: number }
): number {
  if (candidate.parentSlug === current.parentSlug) {
    return 0;
  }
  if (candidate.parentSlug && candidate.parentSlug === current.parentSlug) {
    return 1;
  }
  if (candidate.depth === current.depth) {
    return 2;
  }
  return candidate.kind === "page" ? 3 : 4;
}
