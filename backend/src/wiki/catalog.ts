import { dirname } from "node:path";
import type { CodeGraphNode, JsonObject } from "../types.js";

export type CatalogItem = JsonObject & {
  title?: string;
  slug?: string;
  path?: string | null;
  order?: number;
  kind?: "page" | "category";
  topic?: string;
  source_hints?: string[];
  children?: CatalogItem[];
};

export type GenerationNode = {
  item: CatalogItem;
  parentSlug: string | null;
  slug: string;
  depth: number;
  order: number;
  hasChildren: boolean;
};

export function buildCatalogItems(nodes: CodeGraphNode[]): CatalogItem[] {
  const directories = new Map<string, number>();
  for (const node of nodes) {
    if (node.type !== "file" && node.type !== "config") {
      continue;
    }
    const directory = directoryName(node.file_path);
    directories.set(directory, (directories.get(directory) ?? 0) + 1);
  }
  return [...directories.entries()]
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([directory, count], index) => ({
      title: titleFromSlug(directory),
      slug: slugify(directory),
      path: directory === "root" ? null : directory,
      order: index,
      kind: "page",
      topic: `${count} files`,
      source_hints: directory === "root" ? [] : [directory],
    }));
}

export function catalogStructure(items: CatalogItem[]): JsonObject {
  return { items };
}

export function catalogTitle(repoName: string): string {
  return `${repoName} Wiki`;
}

export function isCatalogItem(value: unknown): value is CatalogItem {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const item = value as Record<string, unknown>;
  return (
    (item.title === undefined || typeof item.title === "string") &&
    (item.slug === undefined || typeof item.slug === "string") &&
    (item.path === undefined ||
      item.path === null ||
      typeof item.path === "string") &&
    (item.kind === undefined ||
      item.kind === "page" ||
      item.kind === "category") &&
    (item.children === undefined ||
      (Array.isArray(item.children) && item.children.every(isCatalogItem)))
  );
}

export function catalogItemsFromStructure(
  structure: JsonObject,
): CatalogItem[] {
  const items = structure.items;
  return Array.isArray(items) ? items.filter(isCatalogItem) : [];
}

export function catalogPageItemsFromStructure(
  structure: JsonObject,
): CatalogItem[] {
  return flattenPageItems(catalogItemsFromStructure(structure));
}

export function catalogGenerationNodesFromStructure(
  structure: JsonObject,
): GenerationNode[] {
  return catalogGenerationNodes(catalogItemsFromStructure(structure));
}

export function catalogGenerationNodes(
  items: CatalogItem[],
  options: { parentSlug?: string | null; depth?: number } = {},
): GenerationNode[] {
  const nodes: GenerationNode[] = [];
  const visit = (
    rawItems: CatalogItem[],
    currentParentSlug: string | null,
    currentDepth: number,
  ) => {
    for (const item of rawItems) {
      const slug = catalogSlug(item);
      const children = catalogItemChildren(item);
      const hasChildren = children.length > 0;
      const kind = String(item.kind ?? "").toLowerCase();
      if (kind === "page" || kind === "category" || !hasChildren) {
        nodes.push({
          item,
          parentSlug: currentParentSlug,
          slug,
          depth: currentDepth,
          order: nodes.length,
          hasChildren,
        });
      }
      visit(children, slug, currentDepth + 1);
    }
  };
  visit(items, options.parentSlug ?? null, options.depth ?? 0);
  return nodes;
}

export function catalogItemChildren(item: CatalogItem): CatalogItem[] {
  return Array.isArray(item.children)
    ? item.children.filter(isCatalogItem)
    : [];
}

export function findCatalogPageItem(
  structure: JsonObject,
  slug: string,
): CatalogItem | null {
  return (
    flattenPageItems(catalogItemsFromStructure(structure)).find(
      (item) => catalogSlug(item) === slug,
    ) ?? null
  );
}

export function findCatalogGenerationNode(
  structure: JsonObject,
  slug: string,
): GenerationNode | null {
  return (
    catalogGenerationNodesFromStructure(structure).find(
      (node) => node.slug === slug,
    ) ?? null
  );
}

export function childPageRecordsForItem<T extends { slug: string }>(
  item: CatalogItem,
  pagesBySlug: Map<string, T>,
): T[] {
  const pages: T[] = [];
  for (const child of catalogItemChildren(item)) {
    const page = pagesBySlug.get(catalogSlug(child));
    if (page) {
      pages.push(page);
    }
  }
  return pages;
}

export function catalogSlug(item: CatalogItem): string {
  return slugify(item.slug || item.path || item.title || "");
}

export function catalogItemTitle(item: CatalogItem): string {
  return item.title || titleFromSlug(catalogSlug(item));
}

function flattenPageItems(items: CatalogItem[]): CatalogItem[] {
  const pages: CatalogItem[] = [];
  for (const item of items) {
    const children = catalogItemChildren(item);
    if (item.kind !== "category") {
      pages.push(item);
    }
    pages.push(...flattenPageItems(children));
  }
  return pages.sort((left, right) => {
    const byOrder = (left.order ?? 0) - (right.order ?? 0);
    return (
      byOrder || catalogItemTitle(left).localeCompare(catalogItemTitle(right))
    );
  });
}

export function slugify(value: string): string {
  return (
    value
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "") || "overview"
  );
}

export function titleFromSlug(value: string): string {
  if (value === "root") {
    return "Overview";
  }
  return value
    .split(/[/-]/)
    .filter(Boolean)
    .map((part) => part.slice(0, 1).toUpperCase() + part.slice(1))
    .join(" ");
}

function directoryName(filePath: string): string {
  const directory = dirname(filePath);
  return directory === "." ? "root" : directory;
}
