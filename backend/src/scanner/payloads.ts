import type { RepoDescriptor, RepoFile } from "../types.js";

export function fileTreePayload(
  repo: RepoDescriptor,
  files: RepoFile[],
): Record<string, unknown> {
  const root: Record<string, unknown> = {
    type: "directory",
    name: repo.name,
    path: "",
    children: [],
  };
  for (const file of files) {
    const parts = file.path.split("/");
    let current = root;
    for (const [index, part] of parts.entries()) {
      const children = current.children as Record<string, unknown>[];
      const path = parts.slice(0, index + 1).join("/");
      const isLeaf = index === parts.length - 1;
      let child = children.find((item) => item.name === part);
      if (!child) {
        child = isLeaf
          ? { type: "file", name: part, path }
          : { type: "directory", name: part, path, children: [] };
        children.push(child);
        children.sort(
          (left, right) =>
            String(left.type).localeCompare(String(right.type)) ||
            String(left.name).localeCompare(String(right.name)),
        );
      }
      if (isLeaf) {
        Object.assign(child, filePayload(file));
      }
      current = child;
    }
  }
  return root;
}

export function filePayload(file: RepoFile): Record<string, unknown> {
  return {
    path: file.path,
    language: file.language,
    is_source: file.is_source,
    size_bytes: file.size_bytes,
    modified_at: file.modified_at,
  };
}
