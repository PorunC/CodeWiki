import type {
  CodeChunk,
  CodeGraphEdge,
  CodeGraphNode,
  JsonObject,
  RepoDescriptor,
} from "../types.js";

export type RelationshipDirection = "callers" | "callees";

export type FileRecord = {
  path: string;
  absolute_path: string;
  language: string | null;
  is_source: boolean;
  size_bytes: number;
  sha256: string;
  modified_at: string;
  type: string;
};

export type FileTreeNode =
  | {
      name: string;
      type: "directory";
      path: string;
      children: FileTreeNode[];
    }
  | {
      name: string;
      type: "file";
      path: string;
      language: string | null;
      is_source: boolean;
    };

export function repoPayload(repo: RepoDescriptor): {
  id: string;
  name: string;
  path: string;
  source_type: string;
  git_url: string;
  commit_hash: string;
} {
  return {
    id: repo.id,
    name: repo.name,
    path: repo.path,
    source_type: repo.source_type,
    git_url: repo.git_url ?? "",
    commit_hash: repo.commit_hash ?? "",
  };
}

export function nodePayload(node: CodeGraphNode): {
  id: string;
  type: string;
  name: string;
  file_path: string;
  start_line: number | null;
  end_line: number | null;
  language: string | null;
  symbol_id: string | null;
  confidence: number;
  provenance: JsonObject;
  metadata: JsonObject;
} {
  return {
    id: node.id,
    type: node.type,
    name: node.name,
    file_path: node.file_path,
    start_line: node.start_line,
    end_line: node.end_line,
    language: node.language,
    symbol_id: node.symbol_id,
    confidence: 1,
    provenance: isJsonObject(node.metadata.provenance)
      ? node.metadata.provenance
      : {},
    metadata: node.metadata,
  };
}

export function edgePayload(edge: CodeGraphEdge): {
  id: string;
  source: string;
  target: string;
  type: string;
  confidence: number;
  confidence_level: string | null;
  reason: string | null;
  is_inferred: boolean;
  provenance: JsonObject;
  metadata: JsonObject;
} {
  return {
    id: edge.id,
    source: edge.source_id,
    target: edge.target_id,
    type: edge.type,
    confidence: edge.confidence,
    confidence_level:
      typeof edge.metadata.confidence_level === "string"
        ? edge.metadata.confidence_level
        : null,
    reason:
      typeof edge.metadata.reason === "string" ? edge.metadata.reason : null,
    is_inferred: edge.is_inferred,
    provenance: isJsonObject(edge.metadata.provenance)
      ? edge.metadata.provenance
      : {},
    metadata: edge.metadata,
  };
}

export function chunkPayload(
  chunk: CodeChunk,
  includeContent: boolean,
): {
  id: string;
  file_path: string;
  start_line: number;
  end_line: number;
  token_count: number;
  content_hash: string;
  content?: string;
} {
  return {
    id: chunk.id,
    file_path: chunk.file_path,
    start_line: chunk.start_line,
    end_line: chunk.end_line,
    token_count: chunk.token_count,
    content_hash: chunk.content_hash,
    ...(includeContent ? { content: chunk.content } : {}),
  };
}

export function fileRecordFromNode(node: CodeGraphNode): FileRecord {
  return {
    path: node.file_path,
    absolute_path: stringMetadata(node.metadata.absolute_path),
    language: node.language,
    is_source: booleanMetadata(node.metadata.is_source, node.type === "file"),
    size_bytes: numberMetadata(node.metadata.size_bytes),
    sha256: node.hash,
    modified_at: stringMetadata(node.metadata.modified_at),
    type: node.type,
  };
}

export function fileTree(
  repoName: string,
  files: Array<{ path: string; language: string | null; is_source: boolean }>,
): {
  name: string;
  type: "directory";
  path: string;
  children: FileTreeNode[];
} {
  const root: {
    name: string;
    type: "directory";
    path: string;
    children: FileTreeNode[];
  } = { name: repoName, type: "directory", path: "", children: [] };
  for (const file of files) {
    const parts = file.path.split("/").filter(Boolean);
    let current = root;
    for (const [index, part] of parts.entries()) {
      const path = parts.slice(0, index + 1).join("/");
      const isLeaf = index === parts.length - 1;
      let child = current.children.find((item) => item.name === part);
      if (!child) {
        child = isLeaf
          ? {
              name: part,
              type: "file",
              path,
              language: file.language,
              is_source: file.is_source,
            }
          : { name: part, type: "directory", path, children: [] };
        current.children.push(child);
        current.children.sort((left, right) =>
          treeSortKey(left).localeCompare(treeSortKey(right)),
        );
      }
      if (child.type === "file") {
        break;
      }
      current = child;
    }
  }
  return root;
}

export function findNode(
  nodes: CodeGraphNode[],
  symbol: string,
): CodeGraphNode | null {
  return (
    nodes.find(
      (node) =>
        node.id === symbol || node.name === symbol || node.symbol_id === symbol,
    ) ?? null
  );
}

export function countBy<T>(
  items: T[],
  key: (item: T) => string,
): Record<string, number> {
  const result: Record<string, number> = {};
  for (const item of items) {
    const value = key(item);
    result[value] = (result[value] ?? 0) + 1;
  }
  return result;
}

export function isLikelyTestFile(
  filePath: string,
  testGlob: string | undefined,
): boolean {
  if (testGlob && filePath.includes(testGlob.replaceAll("*", ""))) {
    return true;
  }
  return /(^|\/)(test|tests|__tests__)\/|(\.|_|-)test\.|(\.|_|-)spec\./i.test(
    filePath,
  );
}

function treeSortKey(node: FileTreeNode): string {
  return `${node.type === "directory" ? "0" : "1"}:${node.name}`;
}

function numberMetadata(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function stringMetadata(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function booleanMetadata(value: unknown, fallback: boolean): boolean {
  return typeof value === "boolean" ? value : fallback;
}

function isJsonObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
