import type { WikiCatalogItem, WikiPageRecord } from "../api/types";

export function sortCatalogItems(items: WikiCatalogItem[]): WikiCatalogItem[] {
  return [...items].sort((left, right) => {
    const leftOrder = typeof left.order === "number" ? left.order : Number.MAX_SAFE_INTEGER;
    const rightOrder = typeof right.order === "number" ? right.order : Number.MAX_SAFE_INTEGER;
    if (leftOrder !== rightOrder) {
      return leftOrder - rightOrder;
    }
    return catalogItemTitle(left).localeCompare(catalogItemTitle(right));
  });
}

export function catalogSlug(item: WikiCatalogItem): string {
  return slugify(item.slug || item.path || item.title || "");
}

export function catalogItemTitle(item: WikiCatalogItem): string {
  return item.title || titleFromSlug(catalogSlug(item));
}

export function firstPageSlugFromItems(
  items: WikiCatalogItem[],
  pageBySlug: Map<string, WikiPageRecord>
): string | null {
  for (const item of sortCatalogItems(items)) {
    const slug = catalogSlug(item);
    if (pageBySlug.has(slug)) {
      return slug;
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
    const slug = catalogSlug(item);
    const children = item.children ?? [];
    if (!pageBySlug.has(slug) && children.length === 0) {
      missingSlugs.push(slug);
    }
    collectMissingPageSlugs(children, pageBySlug, missingSlugs);
  }
}

function slugify(value: string): string {
  return (
    value
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "") || "overview"
  );
}

function titleFromSlug(value: string): string {
  if (value === "root") {
    return "Overview";
  }
  return value
    .split(/[/-]/)
    .filter(Boolean)
    .map((part) => `${part.slice(0, 1).toUpperCase()}${part.slice(1)}`)
    .join(" ");
}
