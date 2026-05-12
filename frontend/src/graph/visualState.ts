import { styleEdgeForSelection } from "./edges";
import { withConnectionAnchors } from "./layout";
import type { FlowEdge, FlowNode, GraphViewMode, VisualGraph } from "./types";

export function applyVisualState(
  nodes: FlowNode[],
  edges: FlowEdge[],
  selectedVisualId: string | null,
  mode: GraphViewMode
): VisualGraph {
  const anchoredNodes = nodes.map(withConnectionAnchors);

  if (!selectedVisualId) {
    return { nodes: anchoredNodes, edges };
  }

  const nodeById = new Map(anchoredNodes.map((node) => [node.id, node]));
  const selectedNode = nodeById.get(selectedVisualId);
  const selectedRawIds = new Set(selectedNode?.data.rawNodeIds ?? []);
  const selectedVisualIds = new Set<string>([selectedVisualId]);

  if (selectedNode?.data.kind === "container") {
    anchoredNodes.forEach((node) => {
      const isChild = node.parentId === selectedVisualId;
      const sharesRawNode = node.data.rawNodeIds.some((rawId) => selectedRawIds.has(rawId));
      if (isChild || sharesRawNode) {
        selectedVisualIds.add(node.id);
      }
    });
  }

  const neighbors = new Set<string>();
  const activeEdgeIds = new Set<string>();
  edges.forEach((edge) => {
    const isActive = selectedVisualIds.has(edge.source) || selectedVisualIds.has(edge.target);
    if (!isActive) {
      return;
    }
    activeEdgeIds.add(edge.id);
    if (!selectedVisualIds.has(edge.source)) {
      neighbors.add(edge.source);
    }
    if (!selectedVisualIds.has(edge.target)) {
      neighbors.add(edge.target);
    }
  });

  return {
    nodes: anchoredNodes.map((node) => {
      const isSelected = node.id === selectedVisualId;
      const isInsideSelectedContainer = selectedNode?.data.kind === "container" && selectedVisualIds.has(node.id);
      const isNeighbor = neighbors.has(node.id) || (isInsideSelectedContainer && !isSelected);
      const isFaded = !isSelected && !isNeighbor;
      return {
        ...node,
        data: {
          ...node.data,
          isSelected,
          isNeighbor,
          isFaded
        }
      };
    }),
    edges: edges.map((edge) => {
      const isActive = activeEdgeIds.has(edge.id);
      return styleEdgeForSelection(edge, isActive, mode);
    })
  };
}

export function pruneHiddenVisualGraph(graph: VisualGraph, hiddenVisualIds: Set<string>): VisualGraph {
  if (hiddenVisualIds.size === 0) {
    return graph;
  }

  const hiddenWithChildren = new Set(hiddenVisualIds);
  let changed = true;
  while (changed) {
    changed = false;
    graph.nodes.forEach((node) => {
      if (node.parentId && hiddenWithChildren.has(node.parentId) && !hiddenWithChildren.has(node.id)) {
        hiddenWithChildren.add(node.id);
        changed = true;
      }
    });
  }

  const nodes = graph.nodes.filter((node) => !hiddenWithChildren.has(node.id));
  const visibleIds = new Set(nodes.map((node) => node.id));
  const edges = graph.edges.filter((edge) => visibleIds.has(edge.source) && visibleIds.has(edge.target));

  return { nodes, edges };
}

export function applyRelatedHighlights(graph: VisualGraph, highlightedRawNodeIds: Set<string>): VisualGraph {
  if (highlightedRawNodeIds.size === 0) {
    return graph;
  }

  return {
    nodes: graph.nodes.map((node) => {
      const isAskRelated = node.data.rawNodeIds.some((rawId) => highlightedRawNodeIds.has(rawId));
      if (!isAskRelated) {
        return node;
      }
      return {
        ...node,
        data: {
          ...node.data,
          isAskRelated,
          isFaded: false
        }
      };
    }),
    edges: graph.edges
  };
}
