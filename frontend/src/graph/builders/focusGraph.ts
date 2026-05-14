import type { GraphResponse } from "../../api/types";
import { FILE_NODE_WIDTH, FOCUS_NODE_HEIGHT } from "../constants";
import { aggregateEdges, toFlowEdge } from "../edges";
import { formatLineRange, isFileLikeNode, nodeSummary } from "../formatters";
import { layoutBoxesCached, nodeSize } from "../layout";
import { toCodeVisualData } from "../nodeData";
import { computeStatsByRawNode } from "../stats";
import { compareBySourceOrder } from "../topology";
import type { ContainmentIndex, FilteredGraph, VisualGraph } from "../types";
import { applyVisualState } from "../visualState";
import { buildOverviewGraph } from "./overviewGraph";

export async function buildFocusGraph(
  graph: GraphResponse,
  filtered: FilteredGraph,
  containment: ContainmentIndex,
  selectedNodeId: string | null,
  selectedVisualId: string | null
): Promise<VisualGraph> {
  const focusNode = selectedNodeId ? containment.nodeById.get(selectedNodeId) : null;
  if (!focusNode || !filtered.nodeIds.has(focusNode.id)) {
    return buildOverviewGraph(graph, filtered, containment, selectedVisualId);
  }

  const relevantNodeIds = new Set<string>([focusNode.id]);
  const relevantEdges = filtered.edges.filter((edge) => {
    const isRelevant = edge.source === focusNode.id || edge.target === focusNode.id;
    if (isRelevant) {
      relevantNodeIds.add(edge.source);
      relevantNodeIds.add(edge.target);
    }
    return isRelevant;
  });

  const fileId = containment.fileByNode.get(focusNode.id);
  if (isFileLikeNode(focusNode)) {
    for (const childId of containment.descendantsByFile.get(focusNode.id) ?? []) {
      if (filtered.nodeIds.has(childId)) {
        relevantNodeIds.add(childId);
      }
    }
  } else if (fileId) {
    relevantNodeIds.add(fileId);
  }

  const rawNodes = [...relevantNodeIds]
    .map((id) => containment.nodeById.get(id))
    .filter((node): node is NonNullable<typeof node> => Boolean(node))
    .sort(compareBySourceOrder);
  const rawNodeIds = new Set(rawNodes.map((node) => node.id));
  const rawEdges = filtered.edges.filter((edge) => rawNodeIds.has(edge.source) && rawNodeIds.has(edge.target));
  const positions = await layoutBoxesCached(
    `focus:${focusNode.id}`,
    rawNodes.map((node) => ({
      id: node.id,
      width: FILE_NODE_WIDTH,
      height: FOCUS_NODE_HEIGHT
    })),
    rawEdges.map((edge) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      type: edge.type,
      count: 1,
      rawEdgeIds: [edge.id],
      hasInferred: edge.is_inferred
    })),
    "LR",
    {
      edgesep: 32,
      marginx: 64,
      marginy: 64,
      nodesep: 138,
      ranksep: 176
    }
  );
  const statsByRawNode = computeStatsByRawNode(graph.edges);

  const nodes = rawNodes.map((node) => ({
    id: node.id,
    type: "code" as const,
    position: positions.get(node.id) ?? { x: 0, y: 0 },
    data: toCodeVisualData(node, {
      containment,
      fileId: containment.fileByNode.get(node.id),
      rawNodeIds: [node.id],
      summary: nodeSummary(node),
      countLabel: isFileLikeNode(node) ? `${containment.descendantsByFile.get(node.id)?.length ?? 0}` : formatLineRange(node),
      stats: statsByRawNode.get(node.id),
      isContained: false,
      isExternal: node.type === "module",
      isFocusMode: true
    }),
    ...nodeSize(FILE_NODE_WIDTH, FOCUS_NODE_HEIGHT),
    selectable: true,
    draggable: false
  }));

  const rawToVisual = new Map(rawNodes.map((node) => [node.id, node.id]));
  const edges = aggregateEdges(rawEdges, rawToVisual, { skipSelfEdges: true }).map((bucket) => toFlowEdge(bucket));

  return applyVisualState(nodes, edges, selectedVisualId, "focus");
}
