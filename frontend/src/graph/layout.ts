import dagre from "@dagrejs/dagre";
import { Position } from "@xyflow/react";

import { GROUP_GAP_X, GROUP_GAP_Y } from "./constants";
import type { FlowNode } from "./types";

export function nodeSize(
  width: number,
  height: number
): Pick<FlowNode, "height" | "initialHeight" | "initialWidth" | "sourcePosition" | "style" | "targetPosition" | "width"> {
  return {
    height,
    initialHeight: height,
    initialWidth: width,
    sourcePosition: Position.Right,
    style: { width, height },
    targetPosition: Position.Left,
    width
  };
}

export function layoutBoxes(
  nodes: Array<{ id: string; width: number; height: number }>,
  edges: Array<{ source: string; target: string }>,
  direction: "LR" | "TB"
): Map<string, { x: number; y: number }> {
  const graph = new dagre.graphlib.Graph();
  graph.setDefaultEdgeLabel(() => ({}));
  graph.setGraph({
    edgesep: 18,
    marginx: 32,
    marginy: 32,
    nodesep: direction === "LR" ? GROUP_GAP_Y : GROUP_GAP_X,
    rankdir: direction,
    ranksep: direction === "LR" ? GROUP_GAP_X : GROUP_GAP_Y
  });

  nodes.forEach((node) => {
    graph.setNode(node.id, { width: node.width, height: node.height });
  });
  edges.forEach((edge) => {
    if (edge.source !== edge.target) {
      graph.setEdge(edge.source, edge.target);
    }
  });
  dagre.layout(graph);

  const positions = new Map<string, { x: number; y: number }>();
  nodes.forEach((node) => {
    const position = graph.node(node.id) as { x: number; y: number } | undefined;
    positions.set(node.id, {
      x: (position?.x ?? 0) - node.width / 2,
      y: (position?.y ?? 0) - node.height / 2
    });
  });

  return positions;
}

export function withConnectionAnchors(node: FlowNode): FlowNode {
  return {
    ...node,
    sourcePosition: Position.Right,
    targetPosition: Position.Left
  };
}
