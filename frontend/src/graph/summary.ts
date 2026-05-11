import type { GraphResponse } from "../api/client";
import type { FilteredGraph, VisualGraph } from "./types";

export function summarizeVisualGraph(
  graph: GraphResponse | null,
  filtered: FilteredGraph,
  visualGraph: VisualGraph
): string {
  if (!graph) {
    return "No graph loaded";
  }
  return `${visualGraph.nodes.length} visual / ${filtered.nodes.length}/${graph.nodes.length} raw nodes / ${visualGraph.edges.length} edges`;
}
