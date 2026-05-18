import type { WikiCatalogItem, WikiPageRecord } from "../api/types";

export function sortCatalogItems(items: WikiCatalogItem[]): WikiCatalogItem[] {
  return [...items].sort((left, right) => {
    const leftOrder = typeof left.order === "number" ? left.order : Number.MAX_SAFE_INTEGER;
    const rightOrder = typeof right.order === "number" ? right.order : Number.MAX_SAFE_INTEGER;
    if (leftOrder !== rightOrder) {
      return leftOrder - rightOrder;
    }
    return left.title.localeCompare(right.title);
  });
}

export function firstPageSlugFromItems(
  items: WikiCatalogItem[],
  pageBySlug: Map<string, WikiPageRecord>
): string | null {
  for (const item of sortCatalogItems(items)) {
    if (pageBySlug.has(item.slug)) {
      return item.slug;
    }
    const childSlug = firstPageSlugFromItems(item.children ?? [], pageBySlug);
    if (childSlug) {
      return childSlug;
    }
  }
  return null;
}

export function missingPageSlugsFromItems(
  items: WikiCatalogItem[],
  pageBySlug: Map<string, WikiPageRecord>
): string[] {
  const missingSlugs: string[] = [];
  collectMissingPageSlugs(items, pageBySlug, missingSlugs);
  return missingSlugs;
}

function collectMissingPageSlugs(
  items: WikiCatalogItem[],
  pageBySlug: Map<string, WikiPageRecord>,
  missingSlugs: string[]
) {
  for (const item of sortCatalogItems(items)) {
    const children = item.children ?? [];
    if (!pageBySlug.has(item.slug) && children.length === 0) {
      missingSlugs.push(item.slug);
    }
    collectMissingPageSlugs(children, pageBySlug, missingSlugs);
  }
}
