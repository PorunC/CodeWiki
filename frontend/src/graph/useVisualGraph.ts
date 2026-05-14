import { useEffect, useMemo, useState } from "react";

import type { GraphResponse } from "../api/types";
import {
  buildContainerDrilldownGraph,
  buildFileDetailGraph,
  buildFocusGraph,
  buildOverviewGraph,
  applyVisualState,
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
  highlightedRawNodeIds,
  flowKey
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
  flowKey: string;
}) {
  const [baseVisualGraph, setBaseVisualGraph] = useState<{ nodes: FlowNode[]; edges: FlowEdge[] }>({
    nodes: [],
    edges: []
  });
  const [activeFlowKey, setActiveFlowKey] = useState(flowKey);
  const [layoutLoading, setLayoutLoading] = useState(false);
  const layoutSelectedFileId = viewMode === "file" ? selectedFileId : null;
  const layoutSelectedNodeId = viewMode === "file" || viewMode === "focus" ? selectedNodeId : null;
  const layoutDrilldownContainer = viewMode === "drilldown" ? drilldownContainer : null;

  useEffect(() => {
    let cancelled = false;

    async function buildGraph() {
      if (!graph) {
        setBaseVisualGraph({ nodes: [], edges: [] });
        setActiveFlowKey(flowKey);
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
            layoutSelectedFileId,
            layoutSelectedNodeId,
            null
          );
        } else if (viewMode === "focus") {
          nextGraph = await buildFocusGraph(graph, filteredGraph, containment, layoutSelectedNodeId, null);
        } else if (viewMode === "drilldown") {
          nextGraph = await buildContainerDrilldownGraph(
            graph,
            filteredGraph,
            containment,
            layoutDrilldownContainer,
            null,
            { densityMode }
          );
        } else {
          nextGraph = await buildOverviewGraph(graph, filteredGraph, containment, null, { densityMode });
        }

        if (!cancelled) {
          setBaseVisualGraph(nextGraph);
          setActiveFlowKey(flowKey);
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
    filteredGraph,
    flowKey,
    graph,
    layoutDrilldownContainer,
    layoutSelectedFileId,
    layoutSelectedNodeId,
    viewMode
  ]);

  const visualGraph = useMemo(() => {
    const visibleGraph = pruneHiddenVisualGraph(baseVisualGraph, hiddenVisualIds);
    const selectedGraph = applyVisualState(visibleGraph.nodes, visibleGraph.edges, selectedVisualId, viewMode);
    return applyRelatedHighlights(selectedGraph, highlightedRawNodeIds);
  }, [baseVisualGraph, hiddenVisualIds, highlightedRawNodeIds, selectedVisualId, viewMode]);

  const selectedVisualData = useMemo(
    () => visualGraph.nodes.find((node) => node.id === selectedVisualId)?.data ?? null,
    [selectedVisualId, visualGraph.nodes]
  );

  return { baseVisualGraph, visualGraph, selectedVisualData, layoutLoading, activeFlowKey };
}
