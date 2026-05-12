import { useMemo } from "react";

import type { GraphResponse } from "../api/client";
import {
  buildFileDetailGraph,
  buildFocusGraph,
  buildOverviewGraph,
  applyRelatedHighlights,
  pruneHiddenVisualGraph,
  type ContainmentIndex,
  type FilteredGraph,
  type FlowEdge,
  type FlowNode,
  type GraphViewMode
} from "./graphModel";

export function useVisualGraph({
  graph,
  filteredGraph,
  containment,
  viewMode,
  selectedFileId,
  selectedNodeId,
  selectedVisualId,
  hiddenVisualIds,
  highlightedRawNodeIds
}: {
  graph: GraphResponse | null;
  filteredGraph: FilteredGraph;
  containment: ContainmentIndex;
  viewMode: GraphViewMode;
  selectedFileId: string | null;
  selectedNodeId: string | null;
  selectedVisualId: string | null;
  hiddenVisualIds: Set<string>;
  highlightedRawNodeIds: Set<string>;
}) {
  const baseVisualGraph = useMemo(() => {
    if (!graph) {
      return { nodes: [] as FlowNode[], edges: [] as FlowEdge[] };
    }

    if (viewMode === "file") {
      return buildFileDetailGraph(graph, filteredGraph, containment, selectedFileId, selectedNodeId, selectedVisualId);
    }

    if (viewMode === "focus") {
      return buildFocusGraph(graph, filteredGraph, containment, selectedNodeId, selectedVisualId);
    }

    return buildOverviewGraph(graph, filteredGraph, containment, selectedVisualId);
  }, [containment, filteredGraph, graph, selectedFileId, selectedNodeId, selectedVisualId, viewMode]);

  const visualGraph = useMemo(
    () => applyRelatedHighlights(pruneHiddenVisualGraph(baseVisualGraph, hiddenVisualIds), highlightedRawNodeIds),
    [baseVisualGraph, hiddenVisualIds, highlightedRawNodeIds]
  );

  const selectedVisualData = useMemo(
    () => visualGraph.nodes.find((node) => node.id === selectedVisualId)?.data ?? null,
    [selectedVisualId, visualGraph.nodes]
  );

  return { baseVisualGraph, visualGraph, selectedVisualData };
}
