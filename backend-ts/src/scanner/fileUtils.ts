import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import type { RepoFile } from "../types.js";

export function knownHashFor(
  file: RepoFile,
  knownHashes?: Map<string, string>,
  knownFileMetadata?: Map<string, [number | null, string | null]>,
  hashPaths?: Set<string>,
): string | null {
  if (!knownHashes?.has(file.path)) {
    return null;
  }
  if (!hashPaths || hashPaths.has(file.path)) {
    return null;
  }
  const [size, modifiedAt] = knownFileMetadata?.get(file.path) ?? [null, null];
  if (size !== file.size_bytes || modifiedAt !== file.modified_at) {
    return null;
  }
  return knownHashes.get(file.path) ?? null;
}

export function isProbablyBinary(path: string): boolean {
  const sample = readFileSync(path).subarray(0, 4096);
  return sample.includes(0);
}

export function sha256File(path: string): string {
  return createHash("sha256").update(readFileSync(path)).digest("hex");
}

export function compareByPath(left: RepoFile, right: RepoFile): number {
  return left.path.localeCompare(right.path);
}
