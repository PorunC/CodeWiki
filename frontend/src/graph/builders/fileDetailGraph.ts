import type { CodeNode, GraphResponse } from "../../api/client";
import {
  FILE_DETAIL_WIDTH,
  FILE_NODE_WIDTH,
  GROUP_HEADER_HEIGHT,
  MAX_PORTAL_NODES
} from "../constants";
import { aggregateEdges, toFlowEdge } from "../edges";
import { nodeSize } from "../layout";
import { toCodeVisualData } from "../nodeData";
import { collectFilePortals, portalToNode } from "../portals";
import { computeStatsByRawNode, computeStatsForNodeIds } from "../stats";
import { nodeTone } from "../styles";
import { compareBySourceOrder } from "../topology";
import type { ContainmentIndex, FilteredGraph, FlowEdge, FlowNode, VisualGraph } from "../types";
import { applyVisualState } from "../visualState";
import { layoutFileDetailSymbols } from "./fileDetailSymbols";

export function buildFileDetailGraph(
  graph: GraphResponse,
  filtered: FilteredGraph,
  containment: ContainmentIndex,
  selectedFileId: string | null,
  selectedNodeId: string | null,
  selectedVisualId: string | null
): VisualGraph {
  const fileNode =
    (selectedFileId ? containment.nodeById.get(selectedFileId) : null) ??
    graph.nodes.find((node) => node.type === "file") ??
    null;

  if (!fileNode) {
    return { nodes: [], edges: [] };
  }

  const descendantIds = containment.descendantsByFile.get(fileNode.id) ?? [];
  const visibleSymbols = descendantIds
    .map((id) => containment.nodeById.get(id))
    .filter((node): node is CodeNode => Boolean(node))
    .filter((node) => filtered.nodeIds.has(node.id))
    .filter((node) => node.type === "class" || node.type === "function" || node.type === "method")
    .sort(compareBySourceOrder);
  const symbolSlots = layoutFileDetailSymbols(visibleSymbols, fileNode.id, containment);

  const fileContainerId = `file-detail:${fileNode.id}`;
  const fileHeight = Math.max(
    320,
    GROUP_HEADER_HEIGHT +
      38 +
      Math.max(0, ...symbolSlots.map((slot) => slot.y + slot.height - GROUP_HEADER_HEIGHT))
  );
  const stats = computeStatsForNodeIds([fileNode.id, ...descendantIds], filtered.edges);
  const nodes: FlowNode[] = [
    {
      id: fileContainerId,
      type: "container",
      position: { x: 0, y: 0 },
      data: {
        kind: "container",
        title: fileNode.name,
        subtitle: "file detail",
        containerType: "file",
        pathLabel: fileNode.file_path ?? fileNode.name,
        countLabel: `${visibleSymbols.length}`,
        statsLabel: `${stats.calls} calls / ${stats.imports} imports`,
        accentColor: nodeTone("file").border,
        fileId: fileNode.id,
        primaryNodeId: fileNode.id,
        rawNodeIds: [fileNode.id, ...descendantIds],
        isSelected: false,
        isNeighbor: false,
        isFaded: false,
        isFocusedViaChild: Boolean(selectedNodeId && selectedNodeId !== fileNode.id),
        isCompact: false
      },
      ...nodeSize(FILE_DETAIL_WIDTH, fileHeight),
      selectable: true,
      draggable: false
    }
  ];

  const statsByRawNode = computeStatsByRawNode(graph.edges);
  symbolSlots.forEach((slot) => {
    const node = slot.node;
    nodes.push({
      id: node.id,
      type: "code",
      parentId: fileContainerId,
      extent: "parent",
      position: {
        x: slot.x,
        y: slot.y
      },
      data: toCodeVisualData(node, {
        containment,
        label: slot.label,
        fileId: fileNode.id,
        rawNodeIds: [node.id],
        summary: slot.summary,
        countLabel: slot.countLabel,
        pathLabel: slot.pathLabel,
        stats: statsByRawNode.get(node.id),
        isContained: true,
        isExternal: false
      }),
      ...nodeSize(slot.width, slot.height),
      selectable: true,
      draggable: false,
      zIndex: 6
    });
  });

  const internalSymbolIds = new Set(visibleSymbols.map((node) => node.id));
  const selectedSymbolId = selectedNodeId && internalSymbolIds.has(selectedNodeId) ? selectedNodeId : null;
  const internalEdges = selectedSymbolId
    ? filtered.edges.filter(
        (edge) =>
          edge.type !== "contains" &&
          (edge.source === selectedSymbolId || edge.target === selectedSymbolId) &&
          internalSymbolIds.has(edge.source) &&
          internalSymbolIds.has(edge.target)
      )
    : [];
  const rawToInternalVisual = new Map<string, string>(visibleSymbols.map((node) => [node.id, node.id]));
  const edges: FlowEdge[] = aggregateEdges(internalEdges, rawToInternalVisual, {
    skipSelfEdges: true
  }).map((bucket) => toFlowEdge(bucket));

  const portals = collectFilePortals(fileNode.id, selectedSymbolId, filtered.edges, containment, graph);
  const outgoing = portals.filter((portal) => portal.direction === "out").slice(0, MAX_PORTAL_NODES);
  const incoming = portals.filter((portal) => portal.direction === "in").slice(0, MAX_PORTAL_NODES);

  outgoing.forEach((portal, index) => {
    nodes.push(portalToNode(portal, { x: FILE_DETAIL_WIDTH + 150, y: 36 + index * 150 }, containment));
    edges.push(toFlowEdge(portal.bucket, selectedSymbolId ?? fileContainerId, portal.visualId));
  });

  incoming.forEach((portal, index) => {
    nodes.push(portalToNode(portal, { x: -FILE_NODE_WIDTH - 150, y: 36 + index * 150 }, containment));
    edges.push(toFlowEdge(portal.bucket, portal.visualId, selectedSymbolId ?? fileContainerId));
  });

  return applyVisualState(nodes, edges, selectedVisualId, "file");
}
