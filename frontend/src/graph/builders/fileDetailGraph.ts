import type { CodeNode, GraphResponse } from "../../api/types";
import {
  FILE_CONTAINER_MIN_HEIGHT,
  FILE_CONTAINER_MIN_WIDTH,
  FILE_NODE_HEIGHT,
  FILE_NODE_WIDTH,
  GROUP_HEADER_HEIGHT,
  GROUP_PADDING_X,
  MAX_PORTAL_NODES,
  SYMBOL_NODE_HEIGHT,
  SYMBOL_NODE_WIDTH
} from "../constants";
import { aggregateEdges, toFlowEdge } from "../edges";
import { fileDisplayName, filePathLabel, formatLineRange, isFileLikeNode, nodeSummary } from "../formatters";
import { layoutBoxesCached, measureLayoutBounds, nodeSize, normalizeLayoutPositions } from "../layout";
import { toCodeVisualData } from "../nodeData";
import { collectFilePortals, portalToNode } from "../portals";
import { computeStatsByRawNode, computeStatsForNodeIds } from "../stats";
import { nodeTone } from "../styles";
import { compareBySourceOrder } from "../topology";
import type { ContainmentIndex, FilteredGraph, FlowEdge, FlowNode, VisualGraph } from "../types";
import { applyVisualState } from "../visualState";

export async function buildFileDetailGraph(
  graph: GraphResponse,
  filtered: FilteredGraph,
  containment: ContainmentIndex,
  selectedFileId: string | null,
  selectedNodeId: string | null,
  selectedVisualId: string | null
): Promise<VisualGraph> {
  const fileNode =
    (selectedFileId ? containment.nodeById.get(selectedFileId) : null) ??
    graph.nodes.find(isFileLikeNode) ??
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
  const symbolBoxes = visibleSymbols.map((node) => ({
    id: node.id,
    width: SYMBOL_NODE_WIDTH,
    height: SYMBOL_NODE_HEIGHT
  }));
  const symbolIds = new Set(visibleSymbols.map((node) => node.id));
  const symbolLayoutEdges = filtered.edges.filter(
    (edge) => edge.type !== "contains" && symbolIds.has(edge.source) && symbolIds.has(edge.target)
  );
  const rawSymbolPositions = await layoutBoxesCached(
    `file-detail:${fileNode.id}:symbols`,
    symbolBoxes,
    symbolLayoutEdges,
    "TB",
    {
      edgesep: 16,
      marginx: 0,
      marginy: 0,
      nodesep: 16,
      ranksep: 34
    }
  );
  const symbolPositions = normalizeLayoutPositions(
    rawSymbolPositions,
    symbolBoxes,
    GROUP_PADDING_X,
    GROUP_HEADER_HEIGHT + 24
  );
  const symbolBounds = measureLayoutBounds(symbolPositions, symbolBoxes);

  const fileContainerId = `file-detail:${fileNode.id}`;
  const fileWidth = Math.max(
    FILE_CONTAINER_MIN_WIDTH,
    symbolBounds.width + GROUP_PADDING_X * 2,
    FILE_NODE_WIDTH + GROUP_PADDING_X
  );
  const fileHeight = Math.max(FILE_CONTAINER_MIN_HEIGHT, symbolBounds.height + GROUP_HEADER_HEIGHT + 42, FILE_NODE_HEIGHT);
  const stats = computeStatsForNodeIds([fileNode.id, ...descendantIds], filtered.edges);
  const nodes: FlowNode[] = [
    {
      id: fileContainerId,
      type: "container",
      position: { x: 0, y: 0 },
      data: {
        kind: "container",
        title: fileDisplayName(fileNode),
        subtitle: fileNode.type === "config" ? "config detail" : "file detail",
        containerType: "file",
        pathLabel: filePathLabel(fileNode),
        countLabel: `${visibleSymbols.length}`,
        statsLabel: `${stats.calls} calls / ${stats.imports} imports`,
        accentColor: nodeTone(fileNode.type).border,
        fileId: fileNode.id,
        primaryNodeId: fileNode.id,
        rawNodeIds: [fileNode.id, ...descendantIds],
        isSelected: false,
        isNeighbor: false,
        isFaded: false,
        isFocusedViaChild: Boolean(selectedNodeId && selectedNodeId !== fileNode.id),
        isCompact: false
      },
      ...nodeSize(fileWidth, fileHeight),
      selectable: true,
      draggable: false
    }
  ];

  const statsByRawNode = computeStatsByRawNode(graph.edges);
  visibleSymbols.forEach((node) => {
    nodes.push({
      id: node.id,
      type: "code",
      parentId: fileContainerId,
      extent: "parent",
      position: symbolPositions.get(node.id) ?? { x: GROUP_PADDING_X, y: GROUP_HEADER_HEIGHT + 24 },
      data: toCodeVisualData(node, {
        containment,
        fileId: fileNode.id,
        rawNodeIds: [node.id],
        summary: nodeSummary(node),
        countLabel: formatLineRange(node),
        pathLabel: filePathLabel(node),
        stats: statsByRawNode.get(node.id),
        isContained: true,
        isExternal: false
      }),
      ...nodeSize(SYMBOL_NODE_WIDTH, SYMBOL_NODE_HEIGHT),
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
    nodes.push(portalToNode(portal, { x: fileWidth + 150, y: 36 + index * 150 }, containment));
    edges.push(toFlowEdge(portal.bucket, selectedSymbolId ?? fileContainerId, portal.visualId));
  });

  incoming.forEach((portal, index) => {
    nodes.push(portalToNode(portal, { x: -FILE_NODE_WIDTH - 150, y: 36 + index * 150 }, containment));
    edges.push(toFlowEdge(portal.bucket, portal.visualId, selectedSymbolId ?? fileContainerId));
  });

  return applyVisualState(nodes, edges, selectedVisualId, "file");
}
