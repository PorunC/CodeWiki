import type { CodeNode, GraphResponse } from "../../api/types";
import { isFileLikeNode } from "../formatters";
import type { SourceRefNavigationDetail } from "../navigationEvents";

export function normalizeSourceRefDetail(
  detail: Partial<SourceRefNavigationDetail> | undefined
): SourceRefNavigationDetail | null {
  if (!detail?.filePath) {
    return null;
  }
  const startLine = Number.isFinite(detail.startLine) ? Number(detail.startLine) : 1;
  const endLine = Number.isFinite(detail.endLine) ? Number(detail.endLine) : startLine;
  return {
    repoId: detail.repoId,
    filePath: detail.filePath,
    startLine: Math.max(1, Math.min(startLine, endLine)),
    endLine: Math.max(1, Math.max(startLine, endLine))
  };
}

export function findBestNodeForSourceRef(
  graph: GraphResponse,
  detail: SourceRefNavigationDetail
): { fileNode: CodeNode; targetNode: CodeNode } | null {
  const fileNode = graph.nodes
    .filter(isFileLikeNode)
    .find((node) => pathsMatch(node.file_path ?? node.name, detail.filePath));
  if (!fileNode) {
    return null;
  }

  const sourceSpan = detail.endLine - detail.startLine + 1;
  const symbols = graph.nodes
    .filter((node) => node.id !== fileNode.id)
    .filter((node) => pathsMatch(node.file_path, detail.filePath))
    .filter((node) => node.start_line != null)
    .map((node) => ({
      node,
      start: node.start_line ?? 1,
      end: node.end_line ?? node.start_line ?? 1
    }));

  const containing = symbols
    .filter(({ start, end }) => start <= detail.startLine && end >= detail.endLine)
    .sort(compareSourceCandidates);
  if (containing[0]) {
    return { fileNode, targetNode: containing[0].node };
  }

  if (sourceSpan <= 80) {
    const overlapping = symbols
      .map((candidate) => ({
        ...candidate,
        overlap: overlapScore(candidate, detail),
        sourceCoverage: overlapScore(candidate, detail) / sourceSpan,
        nodeCoverage: overlapScore(candidate, detail) / Math.max(1, candidate.end - candidate.start + 1)
      }))
      .filter((candidate) => candidate.overlap >= 3)
      .filter((candidate) => candidate.sourceCoverage >= 0.5 || candidate.nodeCoverage >= 0.75)
      .sort(compareOverlapCandidates);
    if (overlapping[0]) {
      return { fileNode, targetNode: overlapping[0].node };
    }
  }

  return { fileNode, targetNode: fileNode };
}

export function findOverviewVisualIdForRawNode(graph: GraphResponse, rawNodeId: string): string | null {
  const nodeById = new Map(graph.nodes.map((node) => [node.id, node]));
  const node = nodeById.get(rawNodeId);
  if (!node) {
    return null;
  }
  if (node.type === "module") {
    return "dependency:external";
  }
  if (isFileLikeNode(node) || node.type === "directory" || node.type === "repository") {
    return node.id;
  }

  const parentByChild = new Map(
    graph.edges
      .filter((edge) => edge.type === "contains")
      .map((edge) => [edge.target, edge.source])
  );
  let currentId: string | undefined = rawNodeId;
  while (currentId) {
    const currentNode = nodeById.get(currentId);
    if (currentNode && isFileLikeNode(currentNode)) {
      return currentNode.id;
    }
    currentId = parentByChild.get(currentId);
  }
  return rawNodeId;
}

export function canShowInFileDetail(node: CodeNode): boolean {
  return isFileLikeNode(node) || node.type === "class" || node.type === "function" || node.type === "method";
}

function compareSourceCandidates(
  left: { start: number; end: number },
  right: { start: number; end: number }
): number {
  const leftSpan = left.end - left.start;
  const rightSpan = right.end - right.start;
  return leftSpan - rightSpan || left.start - right.start;
}

function overlapScore(
  candidate: { start: number; end: number },
  detail: SourceRefNavigationDetail
): number {
  const overlapStart = Math.max(candidate.start, detail.startLine);
  const overlapEnd = Math.min(candidate.end, detail.endLine);
  return Math.max(0, overlapEnd - overlapStart + 1);
}

function compareOverlapCandidates(
  left: { start: number; end: number; overlap: number; sourceCoverage: number; nodeCoverage: number },
  right: { start: number; end: number; overlap: number; sourceCoverage: number; nodeCoverage: number }
): number {
  return (
    right.sourceCoverage - left.sourceCoverage ||
    right.nodeCoverage - left.nodeCoverage ||
    right.overlap - left.overlap ||
    compareSourceCandidates(left, right)
  );
}

function pathsMatch(nodePath: string | null | undefined, sourcePath: string): boolean {
  if (!nodePath) {
    return false;
  }
  const left = normalizePath(nodePath);
  const right = normalizePath(sourcePath);
  return left === right || left.endsWith(`/${right}`) || right.endsWith(`/${left}`);
}

function normalizePath(path: string): string {
  return path.replaceAll("\\", "/").replace(/^\/+/, "").replace(/\/+/g, "/");
}
