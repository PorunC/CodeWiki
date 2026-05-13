import type { CodeEdge, CodeNode } from "../../api/types";
import { fileDisplayName, formatUnknown } from "../graphModel";

export type NodeReference = {
  id: string;
  nodeId: string | null;
  label: string;
  meta: string;
  edgeType?: string;
  metadataValue?: string;
};

export function buildEdgeReferences(
  edges: CodeEdge[],
  edgeType: string,
  metadataKey: string,
  selectedRawIds: Set<string>,
  nodeById: Map<string, CodeNode>
): NodeReference[] {
  const seen = new Set<string>();
  const references: NodeReference[] = [];

  edges
    .filter((edge) => edge.type === edgeType)
    .forEach((edge) => {
      const sourceInside = selectedRawIds.has(edge.source);
      const targetInside = selectedRawIds.has(edge.target);
      const referenceNodeId = sourceInside ? edge.target : edge.source;
      const referenceNode = nodeById.get(referenceNodeId) ?? null;
      const metadataValue = formatUnknown(edge.metadata[metadataKey]);
      const direction = sourceInside && targetInside ? "internal" : sourceInside ? "outgoing" : "incoming";
      const label = referenceNode ? referenceLabel(referenceNode) : metadataValue || referenceNodeId;
      const dedupeKey = `${edgeType}:${referenceNodeId}:${direction}`;

      if (seen.has(dedupeKey)) {
        return;
      }
      seen.add(dedupeKey);

      references.push({
        id: edge.id,
        nodeId: referenceNode?.id ?? null,
        label,
        meta: referenceMeta(referenceNode, direction, metadataValue),
        edgeType,
        metadataValue
      });
    });

  return references.sort(compareReferences);
}

export function buildResolvedMetadataValues(edges: CodeEdge[], edgeType: string, metadataKey: string): Set<string> {
  return new Set(
    edges
      .filter((edge) => edge.type === edgeType)
      .map((edge) => formatUnknown(edge.metadata[metadataKey]))
      .filter(Boolean)
  );
}

export function buildUnresolvedReferences(
  edgeType: string,
  values: string[],
  resolvedValues: Set<string>
): NodeReference[] {
  return [...new Set(values)]
    .filter((value) => !resolvedValues.has(value))
    .map((value) => ({
      id: `metadata:${edgeType}:${value}`,
      nodeId: null,
      label: value,
      meta: "unresolved reference",
      edgeType,
      metadataValue: value
    }));
}

function referenceLabel(node: CodeNode): string {
  if (node.type === "file") {
    return fileDisplayName(node);
  }
  return node.name || node.symbol_id || node.id;
}

function referenceMeta(node: CodeNode | null, direction: string, metadataValue: string): string {
  const parts = [direction];
  if (node) {
    parts.push(node.type);
  }
  if (metadataValue && metadataValue !== node?.name) {
    parts.push(metadataValue);
  }
  return parts.join(" / ");
}

function compareReferences(left: NodeReference, right: NodeReference): number {
  return directionRank(left.meta) - directionRank(right.meta) || left.label.localeCompare(right.label);
}

function directionRank(meta: string): number {
  if (meta.startsWith("outgoing")) {
    return 0;
  }
  if (meta.startsWith("internal")) {
    return 1;
  }
  return 2;
}
