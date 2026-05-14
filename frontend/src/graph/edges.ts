import { MarkerType } from "@xyflow/react";

import type { CodeEdge } from "../api/types";
import { SOURCE_HANDLE_ID, TARGET_HANDLE_ID } from "./constants";
import { graphTypeLabel } from "./formatters";
import { edgeTone } from "./styles";
import type { EdgeBucket, FlowEdge, GraphViewMode } from "./types";

export function aggregateEdges(
  edges: CodeEdge[],
  rawToVisualId: Map<string, string | undefined>,
  options: { skipSelfEdges?: boolean; skipTypes?: Set<string> } = {}
): EdgeBucket[] {
  const buckets = new Map<string, EdgeBucket>();

  edges.forEach((edge) => {
    if (options.skipTypes?.has(edge.type)) {
      return;
    }
    const source = rawToVisualId.get(edge.source);
    const target = rawToVisualId.get(edge.target);
    if (!source || !target) {
      return;
    }
    if (options.skipSelfEdges && source === target) {
      return;
    }

    const key = `${source.length}:${source}\0${target.length}:${target}\0${edge.type}`;
    const existing = buckets.get(key);
    if (existing) {
      existing.count += 1;
      existing.rawEdgeIds.push(edge.id);
      existing.hasInferred = existing.hasInferred || edge.is_inferred;
    } else {
      buckets.set(key, {
        id: `agg:${buckets.size}:${edge.type}`,
        source,
        target,
        type: edge.type,
        count: 1,
        rawEdgeIds: [edge.id],
        hasInferred: edge.is_inferred
      });
    }
  });

  return [...buckets.values()].sort((left, right) => right.count - left.count);
}

export function toFlowEdge(bucket: EdgeBucket, sourceOverride?: string, targetOverride?: string): FlowEdge {
  const tone = edgeTone(bucket.type);
  const countLabel = bucket.count > 1 ? ` x${bucket.count}` : "";
  const isFlowing = bucket.type === "calls" || bucket.hasInferred;

  return {
    id: sourceOverride || targetOverride ? `${bucket.id}:${sourceOverride ?? bucket.source}:${targetOverride ?? bucket.target}` : bucket.id,
    source: sourceOverride ?? bucket.source,
    target: targetOverride ?? bucket.target,
    sourceHandle: SOURCE_HANDLE_ID,
    targetHandle: TARGET_HANDLE_ID,
    data: {
      edgeType: bucket.type,
      count: bucket.count,
      rawEdgeIds: bucket.rawEdgeIds,
      hasInferred: bucket.hasInferred
    },
    animated: isFlowing,
    className: edgeClassName(bucket.type, {
      hasInferred: bucket.hasInferred,
      isFlowing
    }),
    label: `${graphTypeLabel(bucket.type)}${countLabel}`,
    labelBgBorderRadius: 6,
    labelBgPadding: [7, 4],
    labelBgStyle: { fill: "rgba(12, 13, 13, 0.92)" },
    labelStyle: { fill: tone.label, fontSize: 10, fontWeight: 800 },
    markerEnd: { type: MarkerType.ArrowClosed, color: tone.stroke },
    style: {
      stroke: tone.stroke,
      strokeDasharray: bucket.hasInferred ? "7 5" : undefined,
      opacity: bucket.type === "contains" ? 0.45 : 0.78,
      strokeWidth: Math.min(1.4 + Math.log2(bucket.count + 1), 5)
    },
    type: "default"
  };
}

export function styleEdgeForSelection(edge: FlowEdge, isActive: boolean, mode: GraphViewMode): FlowEdge {
  const edgeType = edge.data?.edgeType ?? "related";
  const tone = edgeTone(edgeType);
  const hasInferred = Boolean(edge.data?.hasInferred);
  const baseWidth = numericStrokeWidth(edge.style?.strokeWidth);
  const baseClassOptions = { hasInferred, isFlowing: edgeType === "calls" || hasInferred };

  if (isActive) {
    return {
      ...edge,
      animated: true,
      className: edgeClassName(edgeType, {
        ...baseClassOptions,
        isActive: true
      }),
      labelStyle: { fill: "#e8c49a", fontSize: 11, fontWeight: 900 },
      markerEnd: { type: MarkerType.ArrowClosed, color: "#e8c49a" },
      style: {
        ...edge.style,
        opacity: 1,
        stroke: tone.active,
        strokeDasharray: hasInferred ? "7 5" : undefined,
        strokeWidth: Math.max(2.6, baseWidth + 0.8)
      }
    };
  }

  return {
    ...edge,
    animated: false,
    className: edgeClassName(edgeType, {
      ...baseClassOptions,
      isMuted: true
    }),
    labelStyle: { fill: mode === "focus" ? "rgba(163,151,135,0.16)" : "rgba(163,151,135,0.24)", fontSize: 10, fontWeight: 700 },
    markerEnd: { type: MarkerType.ArrowClosed, color: "rgba(163,151,135,0.18)" },
    style: {
      ...edge.style,
      opacity: mode === "focus" ? 0.06 : 0.1,
      stroke: "rgba(212,165,116,0.12)",
      strokeDasharray: undefined,
      strokeWidth: 1
    }
  };
}

function numericStrokeWidth(value: unknown): number {
  return typeof value === "number" ? value : 1.5;
}

function edgeClassName(
  type: string,
  state: { hasInferred?: boolean; isActive?: boolean; isMuted?: boolean; isFlowing?: boolean } = {}
): string {
  return [
    "code-flow-edge",
    `edge-${type.replaceAll("_", "-").replace(/[^a-zA-Z0-9-]/g, "")}`,
    state.hasInferred ? "is-inferred" : "",
    state.isActive ? "is-active" : "",
    state.isMuted ? "is-muted" : "",
    state.isFlowing ? "is-flowing" : ""
  ]
    .filter(Boolean)
    .join(" ");
}
