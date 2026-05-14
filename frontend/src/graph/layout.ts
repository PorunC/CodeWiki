import { Position } from "@xyflow/react";
import ELK, { type ElkNode } from "elkjs/lib/elk.bundled.js";

import { GROUP_GAP_X, GROUP_GAP_Y } from "./constants";
import type { FlowNode } from "./types";

export type LayoutDirection = "LR" | "TB";
export type LayoutOptions = {
  edgesep?: number;
  marginx?: number;
  marginy?: number;
  nodesep?: number;
  ranksep?: number;
};

const elk = new ELK();
const layoutCache = new Map<string, Map<string, { x: number; y: number }>>();
const MAX_LAYOUT_CACHE_ENTRIES = 128;

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

export async function layoutBoxes(
  nodes: Array<{ id: string; width: number; height: number }>,
  edges: Array<{ source: string; target: string }>,
  direction: LayoutDirection,
  options: LayoutOptions = {}
): Promise<Map<string, { x: number; y: number }>> {
  const nodeIds = new Set(nodes.map((node) => node.id));
  const elkGraph: ElkNode = {
    id: "root",
    layoutOptions: {
      "elk.algorithm": "layered",
      "elk.direction": direction === "LR" ? "RIGHT" : "DOWN",
      "elk.edgeRouting": "ORTHOGONAL",
      "elk.layered.mergeEdges": "true",
      "elk.layered.spacing.edgeNodeBetweenLayers": String(options.edgesep ?? 18),
      "elk.layered.spacing.nodeNodeBetweenLayers": String(
        options.ranksep ?? (direction === "LR" ? GROUP_GAP_X : GROUP_GAP_Y)
      ),
      "elk.padding": `[top=${options.marginy ?? 32},left=${options.marginx ?? 32},bottom=${
        options.marginy ?? 32
      },right=${options.marginx ?? 32}]`,
      "elk.spacing.edgeEdge": String(options.edgesep ?? 18),
      "elk.spacing.nodeNode": String(options.nodesep ?? (direction === "LR" ? GROUP_GAP_Y : GROUP_GAP_X))
    },
    children: nodes.map((node) => ({
      id: node.id,
      width: node.width,
      height: node.height
    })),
    edges: edges
      .filter((edge) => edge.source !== edge.target && nodeIds.has(edge.source) && nodeIds.has(edge.target))
      .map((edge, index) => ({
        id: `edge:${index}:${edge.source}->${edge.target}`,
        sources: [edge.source],
        targets: [edge.target]
      }))
  };

  try {
    const result = await elk.layout(elkGraph);
    const positions = new Map<string, { x: number; y: number }>();
    nodes.forEach((node) => {
      const position = result.children?.find((child) => child.id === node.id);
      positions.set(node.id, {
        x: position?.x ?? 0,
        y: position?.y ?? 0
      });
    });
    return positions;
  } catch (error) {
    console.warn("ELK layout failed; using stable fallback layout.", error);
    return fallbackLayoutBoxes(nodes, direction, options);
  }
}

export async function layoutBoxesCached(
  scope: string,
  nodes: Array<{ id: string; width: number; height: number }>,
  edges: Array<{ source: string; target: string }>,
  direction: LayoutDirection,
  options: LayoutOptions = {}
): Promise<Map<string, { x: number; y: number }>> {
  const key = layoutCacheKey(scope, nodes, edges, direction, options);
  const cached = layoutCache.get(key);
  if (cached) {
    return clonePositions(cached);
  }

  const positions = await layoutBoxes(nodes, edges, direction, options);
  layoutCache.set(key, clonePositions(positions));
  if (layoutCache.size > MAX_LAYOUT_CACHE_ENTRIES) {
    const oldestKey = layoutCache.keys().next().value;
    if (oldestKey) {
      layoutCache.delete(oldestKey);
    }
  }
  return positions;
}

export function withConnectionAnchors(node: FlowNode): FlowNode {
  return {
    ...node,
    sourcePosition: Position.Right,
    targetPosition: Position.Left
  };
}

function fallbackLayoutBoxes(
  nodes: Array<{ id: string; width: number; height: number }>,
  direction: LayoutDirection,
  options: LayoutOptions
): Map<string, { x: number; y: number }> {
  const positions = new Map<string, { x: number; y: number }>();
  const marginx = options.marginx ?? 32;
  const marginy = options.marginy ?? 32;
  const ranksep = options.ranksep ?? (direction === "LR" ? GROUP_GAP_X : GROUP_GAP_Y);
  let cursorX = marginx;
  let cursorY = marginy;

  nodes.forEach((node) => {
    positions.set(node.id, { x: cursorX, y: cursorY });
    if (direction === "LR") {
      cursorX += node.width + ranksep;
    } else {
      cursorY += node.height + ranksep;
    }
  });

  return positions;
}

function layoutCacheKey(
  scope: string,
  nodes: Array<{ id: string; width: number; height: number }>,
  edges: Array<{ source: string; target: string }>,
  direction: LayoutDirection,
  options: LayoutOptions
): string {
  const nodePart = nodes
    .map((node) => `${node.id}:${node.width}x${node.height}`)
    .sort()
    .join("|");
  const edgePart = edges
    .filter((edge) => edge.source !== edge.target)
    .map((edge) => `${edge.source}->${edge.target}`)
    .sort()
    .join("|");
  const optionPart = Object.entries(options)
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([key, value]) => `${key}:${value}`)
    .join("|");
  return `${scope}:${direction}:${optionPart}:${nodePart}:${edgePart}`;
}

function clonePositions(positions: Map<string, { x: number; y: number }>): Map<string, { x: number; y: number }> {
  return new Map([...positions].map(([id, position]) => [id, { ...position }]));
}
