import { useEffect, useMemo, useState } from "react";

import type { GraphResponse } from "../api/types";
import {
  buildContainerDrilldownGraph,
  buildFileDetailGraph,
  buildFocusGraph,
  buildOverviewGraph,
  applyRelatedHighlights,
  pruneHiddenVisualGraph,
  type ContainmentIndex,
  type DrilldownContainerSelection,
  type FilteredGraph,
  type FlowEdge,
  type FlowNode,
  type GraphDensityMode,
  type GraphViewMode
} from "./graphModel";

export function useVisualGraph({
  graph,
  filteredGraph,
  containment,
  viewMode,
  densityMode,
  selectedFileId,
  selectedNodeId,
  drilldownContainer,
  selectedVisualId,
  hiddenVisualIds,
  highlightedRawNodeIds
}: {
  graph: GraphResponse | null;
  filteredGraph: FilteredGraph;
  containment: ContainmentIndex;
  viewMode: GraphViewMode;
  densityMode: GraphDensityMode;
  selectedFileId: string | null;
  selectedNodeId: string | null;
  drilldownContainer: DrilldownContainerSelection | null;
  selectedVisualId: string | null;
  hiddenVisualIds: Set<string>;
  highlightedRawNodeIds: Set<string>;
}) {
  const [baseVisualGraph, setBaseVisualGraph] = useState<{ nodes: FlowNode[]; edges: FlowEdge[] }>({
    nodes: [],
    edges: []
  });
  const [layoutLoading, setLayoutLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function buildGraph() {
      if (!graph) {
        setBaseVisualGraph({ nodes: [], edges: [] });
        setLayoutLoading(false);
        return;
      }

      setLayoutLoading(true);
      try {
        let nextGraph: { nodes: FlowNode[]; edges: FlowEdge[] };
        if (viewMode === "file") {
          nextGraph = buildFileDetailGraph(
            graph,
            filteredGraph,
            containment,
            selectedFileId,
            selectedNodeId,
            selectedVisualId
          );
        } else if (viewMode === "focus") {
          nextGraph = await buildFocusGraph(graph, filteredGraph, containment, selectedNodeId, selectedVisualId);
        } else if (viewMode === "drilldown") {
          nextGraph = await buildContainerDrilldownGraph(
            graph,
            filteredGraph,
            containment,
            drilldownContainer,
            selectedVisualId,
            { densityMode }
          );
        } else {
          nextGraph = await buildOverviewGraph(graph, filteredGraph, containment, selectedVisualId, { densityMode });
        }

        if (!cancelled) {
          setBaseVisualGraph(nextGraph);
        }
      } catch (error) {
        console.error("Graph layout failed.", error);
        if (!cancelled) {
          setBaseVisualGraph({ nodes: [], edges: [] });
        }
      } finally {
        if (!cancelled) {
          setLayoutLoading(false);
        }
      }
    }

    void buildGraph();
    return () => {
      cancelled = true;
    };
  }, [
    containment,
    densityMode,
    drilldownContainer,
    filteredGraph,
    graph,
    selectedFileId,
    selectedNodeId,
    selectedVisualId,
    viewMode
  ]);

  const visualGraph = useMemo(
    () => applyRelatedHighlights(pruneHiddenVisualGraph(baseVisualGraph, hiddenVisualIds), highlightedRawNodeIds),
    [baseVisualGraph, hiddenVisualIds, highlightedRawNodeIds]
  );

  const selectedVisualData = useMemo(
    () => visualGraph.nodes.find((node) => node.id === selectedVisualId)?.data ?? null,
    [selectedVisualId, visualGraph.nodes]
  );

  return { baseVisualGraph, visualGraph, selectedVisualData, layoutLoading };
}
