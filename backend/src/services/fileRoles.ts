import type { CodeGraphEdge, CodeGraphNode } from "../types.js";

const LOCKFILE_NAMES = new Set([
  "uv.lock",
  "package-lock.json",
  "pnpm-lock.yaml",
  "yarn.lock",
]);

const GENERATED_DIR_NAMES = new Set([
  ".next",
  ".nuxt",
  ".svelte-kit",
  "build",
  "coverage",
  "dist",
  "htmlcov",
  "out",
  "target",
]);

const GENERATED_FILE_SUFFIXES = [
  ".bundle.js",
  ".bundle.css",
  ".d.ts",
  ".generated.py",
  ".generated.ts",
  ".generated.tsx",
  ".min.css",
  ".min.js",
];

const VENDOR_DIR_NAMES = new Set([
  ".git",
  ".hg",
  ".svn",
  ".venv",
  "node_modules",
  "site-packages",
  "vendor",
  "vendors",
  "venv",
]);

const TEST_DIR_NAMES = new Set([
  "__tests__",
  "e2e",
  "spec",
  "specs",
  "test",
  "tests",
]);

export function normalizeFilePath(filePath: string): string {
  return filePath
    .replace(/\\/g, "/")
    .replace(/^\/+|\/+$/g, "")
    .trim();
}

export function isTestFile(filePath: string): boolean {
  const normalized = normalizeFilePath(filePath).toLowerCase();
  const name = normalized.split("/").pop() ?? "";
  const parts = new Set(normalized.split("/").filter(Boolean));
  return (
    name.startsWith("test_") ||
    name.endsWith("_test.py") ||
    name.endsWith("_test.go") ||
    name.includes(".test.") ||
    name.includes(".spec.") ||
    intersects(parts, TEST_DIR_NAMES)
  );
}

export function isGeneratedFile(filePath: string): boolean {
  const normalized = normalizeFilePath(filePath).toLowerCase();
  const name = normalized.split("/").pop() ?? "";
  const parts = new Set(normalized.split("/").filter(Boolean));
  return (
    LOCKFILE_NAMES.has(name) ||
    GENERATED_FILE_SUFFIXES.some((suffix) => name.endsWith(suffix)) ||
    intersects(parts, GENERATED_DIR_NAMES)
  );
}

export function isVendorFile(filePath: string): boolean {
  return intersects(
    new Set(
      normalizeFilePath(filePath).toLowerCase().split("/").filter(Boolean),
    ),
    VENDOR_DIR_NAMES,
  );
}

export function isWikiNoiseFile(filePath: string): boolean {
  return (
    isTestFile(filePath) || isGeneratedFile(filePath) || isVendorFile(filePath)
  );
}

export function isWikiNoiseNode(node: CodeGraphNode): boolean {
  if (node.metadata.external === true) {
    return true;
  }
  return Boolean(node.file_path && isWikiNoiseFile(node.file_path));
}

export function filterWikiGraph(
  nodes: CodeGraphNode[],
  edges: CodeGraphEdge[],
): { nodes: CodeGraphNode[]; edges: CodeGraphEdge[] } {
  const filteredNodes = nodes.filter((node) => !isWikiNoiseNode(node));
  const nodeIds = new Set(filteredNodes.map((node) => node.id));
  return {
    nodes: filteredNodes,
    edges: edges.filter(
      (edge) => nodeIds.has(edge.source_id) && nodeIds.has(edge.target_id),
    ),
  };
}

function intersects(left: Set<string>, right: Set<string>): boolean {
  for (const value of left) {
    if (right.has(value)) {
      return true;
    }
  }
  return false;
}
