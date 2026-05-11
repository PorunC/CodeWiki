import type { CodeEdge, CodeNode, GraphResponse } from "../api/client";
import { FILE_NODE_HEIGHT, FILE_NODE_WIDTH } from "./constants";
import { nodeSize } from "./layout";
import { toCodeVisualData } from "./nodeData";
import { nodeTone } from "./styles";
import type { ContainmentIndex, FlowNode, Portal } from "./types";

export function collectFilePortals(
  fileId: string,
  selectedSymbolId: string | null,
  edges: CodeEdge[],
  containment: ContainmentIndex,
  graph: GraphResponse
): Portal[] {
  const fileRawIds = new Set([fileId, ...(containment.descendantsByFile.get(fileId) ?? [])]);
  const sourceIds = selectedSymbolId ? new Set([selectedSymbolId]) : fileRawIds;
  const moduleVisualId = "portal:dependency";
  const rawToVisual = new Map<string, string>();
  const portalNodes = new Map<string, CodeNode | null>();

  graph.nodes.forEach((node) => {
    if (node.type === "module") {
      rawToVisual.set(node.id, moduleVisualId);
      portalNodes.set(moduleVisualId, null);
      return;
    }

    const nodeFileId = containment.fileByNode.get(node.id);
    if (nodeFileId && nodeFileId !== fileId) {
      const visualId = `portal:${nodeFileId}`;
      rawToVisual.set(node.id, visualId);
      portalNodes.set(visualId, containment.nodeById.get(nodeFileId) ?? null);
    }
  });

  const buckets = new Map<string, Portal>();
  edges
    .filter((edge) => edge.type !== "contains")
    .forEach((edge) => {
      const sourceInside = sourceIds.has(edge.source);
      const targetInside = sourceIds.has(edge.target);
      if (sourceInside === targetInside) {
        return;
      }

      const externalRawId = sourceInside ? edge.target : edge.source;
      const baseVisualId = rawToVisual.get(externalRawId);
      if (!baseVisualId) {
        return;
      }

      const direction: "in" | "out" = sourceInside ? "out" : "in";
      const visualId = `portal:${direction}:${baseVisualId}`;
      const key = `${direction}:${visualId}:${edge.type}`;
      const existing = buckets.get(key);
      if (existing) {
        existing.bucket.count += 1;
        existing.bucket.rawEdgeIds.push(edge.id);
        existing.bucket.hasInferred = existing.bucket.hasInferred || edge.is_inferred;
      } else {
        buckets.set(key, {
          visualId,
          direction,
          node: portalNodes.get(baseVisualId) ?? null,
          bucket: {
            id: `portal-edge:${buckets.size}:${direction}:${edge.type}`,
            source: direction === "out" ? fileId : visualId,
            target: direction === "out" ? visualId : fileId,
            type: edge.type,
            count: 1,
            rawEdgeIds: [edge.id],
            hasInferred: edge.is_inferred
          }
        });
      }
    });

  return [...buckets.values()].sort((left, right) => right.bucket.count - left.bucket.count);
}

export function portalToNode(
  portal: Portal,
  position: { x: number; y: number },
  containment: ContainmentIndex
): FlowNode {
  if (!portal.node) {
    return {
      id: portal.visualId,
      type: "container",
      position,
      data: {
        kind: "container",
        title: "External Dependencies",
        subtitle: "module portal",
        containerType: "dependency",
        pathLabel: "collapsed import target",
        countLabel: `${portal.bucket.count}`,
        statsLabel: `${portal.direction === "out" ? "outgoing" : "incoming"} ${portal.bucket.type}`,
        accentColor: nodeTone("module").border,
        rawNodeIds: portal.bucket.rawEdgeIds,
        isSelected: false,
        isNeighbor: false,
        isFaded: false,
        isFocusedViaChild: false,
        isCompact: true
      },
      ...nodeSize(FILE_NODE_WIDTH, 134),
      selectable: true,
      draggable: false
    };
  }

  const descendants = containment.descendantsByFile.get(portal.node.id) ?? [];
  return {
    id: portal.visualId,
    type: "code",
    position,
    data: toCodeVisualData(portal.node, {
      containment,
      fileId: portal.node.id,
      rawNodeIds: [portal.node.id, ...descendants],
      summary: `${portal.bucket.count} ${portal.bucket.type} ${portal.direction === "out" ? "from this file" : "into this file"}`,
      countLabel: `${descendants.length}`,
      statsLabel: `${portal.direction === "out" ? "outgoing" : "incoming"} edge group`,
      isContained: false,
      isExternal: true
    }),
    ...nodeSize(FILE_NODE_WIDTH, FILE_NODE_HEIGHT),
    selectable: true,
    draggable: false
  };
}
