export type FileTreeLike = {
  name?: unknown;
  type?: unknown;
  children?: unknown;
};

export function formatFileTree(node: FileTreeLike, prefix = ""): string {
  const name = typeof node.name === "string" ? node.name : "";
  const type = typeof node.type === "string" ? node.type : "";
  const line = `${prefix}${name}${type === "directory" ? "/" : ""}`;
  const children = Array.isArray(node.children)
    ? node.children.filter(isFileTreeLike)
    : [];
  const childLines = children.map((child) =>
    formatFileTree(child, `${prefix}  `),
  );
  return [line, ...childLines].join("\n");
}

function isFileTreeLike(value: unknown): value is FileTreeLike {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
