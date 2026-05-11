import type { CodeEdge } from "../api/client";
import type { NodeStats } from "./types";

export function computeStatsByRawNode(edges: CodeEdge[]): Map<string, NodeStats> {
  const stats = new Map<string, NodeStats>();
  const ensure = (id: string) => {
    const current = stats.get(id);
    if (current) {
      return current;
    }
    const next = { incoming: 0, outgoing: 0, calls: 0, imports: 0 };
    stats.set(id, next);
    return next;
  };

  edges.forEach((edge) => {
    const source = ensure(edge.source);
    const target = ensure(edge.target);
    source.outgoing += 1;
    target.incoming += 1;
    if (edge.type === "calls") {
      source.calls += 1;
    }
    if (edge.type === "imports") {
      source.imports += 1;
    }
  });

  return stats;
}

export function computeStatsForNodeIds(nodeIds: string[], edges: CodeEdge[]): NodeStats {
  const ids = new Set(nodeIds);
  const stats = { incoming: 0, outgoing: 0, calls: 0, imports: 0 };

  edges.forEach((edge) => {
    const sourceInside = ids.has(edge.source);
    const targetInside = ids.has(edge.target);
    if (sourceInside && !targetInside) {
      stats.outgoing += 1;
    }
    if (!sourceInside && targetInside) {
      stats.incoming += 1;
    }
    if (sourceInside && edge.type === "calls") {
      stats.calls += 1;
    }
    if (sourceInside && edge.type === "imports") {
      stats.imports += 1;
    }
  });

  return stats;
}
