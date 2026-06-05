import { createHash } from "node:crypto";

export function digest(value: string): string {
  return createHash("sha1").update(value).digest("hex");
}

export function pushMap<T>(map: Map<string, T[]>, key: string, value: T): void {
  const items = map.get(key) ?? [];
  items.push(value);
  map.set(key, items);
}
