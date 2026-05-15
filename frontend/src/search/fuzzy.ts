import Fuse from "fuse.js";

type FuseKey<T> = keyof T & string;

export function fuzzySearch<T>(
  items: T[],
  query: string,
  keys: Array<FuseKey<T>>,
  options: { threshold?: number } = {}
): T[] {
  const normalized = query.trim();
  if (!normalized) {
    return items;
  }

  return new Fuse(items, {
    ignoreLocation: true,
    keys,
    minMatchCharLength: 1,
    threshold: options.threshold ?? 0.34
  })
    .search(normalized)
    .map((result) => result.item);
}
