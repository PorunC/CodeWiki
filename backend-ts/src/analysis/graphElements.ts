import type { CodeGraphEdge, CodeGraphNode, JsonObject } from "../types.js";
import { digest } from "./graphUtils.js";

export type CodeNodeOptions = Omit<
  CodeGraphNode,
  "id" | "repo_id" | "summary"
> & {
  summary?: string | null;
};

export function codeNode(
  repoId: string,
  options: CodeNodeOptions,
): CodeGraphNode {
  return {
    id: digest(
      `${repoId}:node:${options.type}:${options.file_path}:${options.name}:${options.start_line ?? ""}`,
    ),
    repo_id: repoId,
    summary: options.summary ?? null,
    ...options,
  };
}

export function codeEdge(
  repoId: string,
  sourceId: string,
  targetId: string,
  type: string,
  metadata: JsonObject = {},
): CodeGraphEdge {
  return {
    id: digest(
      `${repoId}:edge:${type}:${sourceId}:${targetId}:${JSON.stringify(metadata)}`,
    ),
    repo_id: repoId,
    source_id: sourceId,
    target_id: targetId,
    type,
    confidence: 1,
    weight: 1,
    is_inferred: type === "calls",
    metadata,
  };
}

export function dedupeNodes(nodes: CodeGraphNode[]): CodeGraphNode[] {
  return [...new Map(nodes.map((node) => [node.id, node])).values()];
}

export function dedupeEdges(edges: CodeGraphEdge[]): CodeGraphEdge[] {
  return [...new Map(edges.map((edge) => [edge.id, edge])).values()];
}
