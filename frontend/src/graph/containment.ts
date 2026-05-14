import type { CodeNode, GraphResponse } from "../api/types";
import { compareBySourceOrder } from "./fileGrouping";
import { isFileLikeNode } from "./formatters";
import type { ContainmentIndex, VisualNodeData } from "./types";

export function nearestAncestorOfType(
  nodeId: string,
  type: string,
  containment: ContainmentIndex
): string | null {
  const visited = new Set<string>();
  let current = containment.parentByChild.get(nodeId);

  while (current && !visited.has(current)) {
    visited.add(current);
    const node = containment.nodeById.get(current);
    if (node?.type === type) {
      return node.id;
    }
    current = containment.parentByChild.get(current);
  }

  return null;
}

export function deriveContainment(graph: GraphResponse | null): ContainmentIndex {
  const nodeById = new Map<string, CodeNode>();
  const childrenByParent = new Map<string, string[]>();
  const parentByChild = new Map<string, string>();
  const fileByNode = new Map<string, string>();
  const descendantsByFile = new Map<string, string[]>();

  if (!graph) {
    return { nodeById, childrenByParent, parentByChild, fileByNode, descendantsByFile };
  }

  graph.nodes.forEach((node) => {
    nodeById.set(node.id, node);
  });

  graph.edges
    .filter((edge) => edge.type === "contains")
    .forEach((edge) => {
      const children = childrenByParent.get(edge.source) ?? [];
      children.push(edge.target);
      childrenByParent.set(edge.source, children);
      if (!parentByChild.has(edge.target)) {
        parentByChild.set(edge.target, edge.source);
      }
    });

  const fileNodes = graph.nodes.filter(isFileLikeNode);
  fileNodes.forEach((file) => {
    fileByNode.set(file.id, file.id);
    descendantsByFile.set(file.id, []);
  });

  graph.nodes.forEach((node) => {
    const fileId = findFileAncestor(node.id, nodeById, parentByChild, fileNodes);
    if (fileId) {
      fileByNode.set(node.id, fileId);
      if (node.id !== fileId) {
        const descendants = descendantsByFile.get(fileId) ?? [];
        descendants.push(node.id);
        descendantsByFile.set(fileId, descendants);
      }
    }
  });

  descendantsByFile.forEach((ids) => {
    ids.sort((left, right) => compareBySourceOrder(nodeById.get(left), nodeById.get(right)));
  });

  return { nodeById, childrenByParent, parentByChild, fileByNode, descendantsByFile };
}

function findFileAncestor(
  nodeId: string,
  nodeById: Map<string, CodeNode>,
  parentByChild: Map<string, string>,
  fileNodes: CodeNode[]
): string | null {
  const node = nodeById.get(nodeId);
  if (!node) {
    return null;
  }
  if (isFileLikeNode(node)) {
    return node.id;
  }

  const visited = new Set<string>();
  let currentId: string | undefined = nodeId;
  while (currentId && !visited.has(currentId)) {
    visited.add(currentId);
    const parentId = parentByChild.get(currentId);
    if (!parentId) {
      break;
    }
    const parent = nodeById.get(parentId);
    if (parent && isFileLikeNode(parent)) {
      return parent.id;
    }
    currentId = parentId;
  }

  if (node.file_path) {
    return fileNodes.find((file) => file.file_path === node.file_path)?.id ?? null;
  }

  return null;
}

export function getPrimaryNode(visualData: VisualNodeData | null, containment: ContainmentIndex): CodeNode | null {
  if (!visualData) {
    return null;
  }
  if (visualData.kind === "code") {
    return visualData.codeNode;
  }
  if (visualData.primaryNodeId) {
    return containment.nodeById.get(visualData.primaryNodeId) ?? null;
  }
  return visualData.rawNodeIds.map((id) => containment.nodeById.get(id)).find(Boolean) ?? null;
}
