import type { GraphResponse } from "../api/types";
import type { FilteredGraph } from "./types";

const DEFAULT_HIDDEN_EDGE_TYPES = new Set(["define", "defines"]);
const READABLE_EDGE_TYPES = new Set(["calls", "routes_to", "imports", "exports", "inherits"]);

export function filterRawGraph(
  graph: GraphResponse | null,
  selectedNodeTypes: Set<string>,
  selectedEdgeTypes: Set<string>,
  showInferredCalls: boolean
): FilteredGraph {
  if (!graph) {
    return { nodes: [], edges: [], nodeIds: new Set() };
  }

  const nodes = graph.nodes.filter((node) => selectedNodeTypes.has(node.type));
  const nodeIds = new Set(nodes.map((node) => node.id));
  const edges = graph.edges.filter((edge) => {
    if (!selectedEdgeTypes.has(edge.type)) {
      return false;
    }
    if (!showInferredCalls && edge.type === "calls" && edge.is_inferred) {
      return false;
    }
    return nodeIds.has(edge.source) && nodeIds.has(edge.target);
  });

  return { nodes, edges, nodeIds };
}

export function collectTypes(items: Array<{ type: string }>): string[] {
  return [...new Set(items.map((item) => item.type))].sort((left, right) => left.localeCompare(right));
}

export function defaultReadableEdgeTypes(edgeTypes: string[]): Set<string> {
  const selected = withoutDefaultHiddenEdgeTypes(edgeTypes.filter((type) => READABLE_EDGE_TYPES.has(type)));
  return new Set(selected.length > 0 ? selected : withoutDefaultHiddenEdgeTypes(edgeTypes));
}

export function defaultFullEdgeTypes(edgeTypes: string[]): Set<string> {
  const selected = withoutDefaultHiddenEdgeTypes(edgeTypes);
  return new Set(selected.length > 0 ? selected : edgeTypes);
}

function withoutDefaultHiddenEdgeTypes(edgeTypes: string[]): string[] {
  return edgeTypes.filter((type) => !DEFAULT_HIDDEN_EDGE_TYPES.has(type));
}

export function toggleSetValue(values: Set<string>, value: string): Set<string> {
  const nextValues = new Set(values);
  if (nextValues.has(value)) {
    nextValues.delete(value);
  } else {
    nextValues.add(value);
  }
  return nextValues;
}

export function filterKey(values: Set<string>): string {
  return [...values].sort().join("|");
}
