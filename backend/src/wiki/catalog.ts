import { dirname } from "node:path";
import type { CodeGraphNode, JsonObject } from "../types.js";

export type CatalogItem = JsonObject & {
  title: string;
  slug: string;
  path: string | null;
  order: number;
  kind: "page" | "category";
  topic: string;
  source_hints?: string[];
  children?: CatalogItem[];
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
    typeof item.title === "string" &&
    typeof item.slug === "string" &&
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
      (item) => item.slug === slug,
    ) ?? null
  );
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
    return byOrder || left.title.localeCompare(right.title);
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
