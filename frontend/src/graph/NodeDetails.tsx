import { useMemo } from "react";

import type { CodeEdge, CodeNode, GraphResponse } from "../api/client";
import {
  fileDisplayName,
  computeStatsForNodeIds,
  formatLineRange,
  formatUnknown,
  getPrimaryNode,
  listFromUnknown,
  type ContainmentIndex,
  type VisualNodeData
} from "./graphModel";

export function NodeDetails({
  visualData,
  node,
  edges,
  graph,
  containment,
  onNavigateToNode
}: {
  visualData: VisualNodeData | null;
  node: CodeNode | null;
  edges: CodeEdge[];
  graph: GraphResponse | null;
  containment: ContainmentIndex;
  onNavigateToNode: (nodeId: string, edgeType?: string) => void;
}) {
  const rawNodeIds = visualData?.rawNodeIds ?? (node ? [node.id] : []);
  const visualStats = useMemo(
    () => (graph ? computeStatsForNodeIds(rawNodeIds, graph.edges) : { incoming: 0, outgoing: 0, calls: 0, imports: 0 }),
    [graph, rawNodeIds]
  );

  if (!visualData && !node) {
    return (
      <aside className="node-details">
        <div className="detail-empty">Select a node to inspect it.</div>
      </aside>
    );
  }

  if (visualData?.kind === "container" && !node) {
    return (
      <aside className="node-details">
        <div className="detail-heading">
          <span className="node-type-pill">{visualData.containerType}</span>
          <h3>{visualData.title}</h3>
        </div>
        <dl className="detail-list">
          <DetailItem label="Path" value={visualData.pathLabel || "Synthetic graph group"} />
          <DetailItem label="Items" value={visualData.countLabel} />
          <DetailItem label="Edges" value={`${visualStats.incoming} in / ${visualStats.outgoing} out`} />
          <DetailItem label="Raw nodes" value={`${rawNodeIds.length}`} />
        </dl>
      </aside>
    );
  }

  const detailNode = node ?? getPrimaryNode(visualData, containment);
  if (!detailNode) {
    return (
      <aside className="node-details">
        <div className="detail-empty">No node metadata available.</div>
      </aside>
    );
  }

  const descendantCount =
    detailNode.type === "file" ? containment.descendantsByFile.get(detailNode.id)?.length ?? 0 : 0;
  const nodeById = new Map(graph?.nodes.map((graphNode) => [graphNode.id, graphNode]) ?? []);
  const selectedRawIds = new Set(rawNodeIds);
  const imports = buildEdgeReferences(edges, "imports", "import", selectedRawIds, nodeById);
  const calls = [
    ...buildEdgeReferences(edges, "calls", "call", selectedRawIds, nodeById),
    ...buildUnresolvedReferences(
      "calls",
      listFromUnknown(detailNode.metadata.calls),
      buildResolvedMetadataValues(edges, "calls", "call")
    )
  ];

  return (
    <aside className="node-details">
      <div className="detail-heading">
        <span className="node-type-pill">{detailNode.type}</span>
        <h3>{detailNode.type === "file" ? fileDisplayName(detailNode) : detailNode.name}</h3>
      </div>

      <dl className="detail-list">
        <DetailItem label="File" value={detailNode.file_path || "External or repository scope"} />
        <DetailItem label="Lines" value={formatLineRange(detailNode)} />
        <DetailItem label="Language" value={detailNode.language || "Unknown"} />
        <DetailItem label="Edges" value={`${visualStats.incoming} in / ${visualStats.outgoing} out`} />
        {descendantCount > 0 ? <DetailItem label="Symbols" value={`${descendantCount}`} /> : null}
        {detailNode.symbol_id ? <DetailItem label="Symbol" value={detailNode.symbol_id} /> : null}
      </dl>

      <ReferenceSection title="Imports" references={imports} onNavigateToNode={onNavigateToNode} />
      <ReferenceSection title="Calls" references={calls} onNavigateToNode={onNavigateToNode} />
      <RawMetadata metadata={detailNode.metadata} />
    </aside>
  );
}

type NodeReference = {
  id: string;
  nodeId: string | null;
  label: string;
  meta: string;
  edgeType?: string;
  metadataValue?: string;
};

function DetailItem({ label, value }: { label: string; value: string }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </>
  );
}

function ReferenceSection({
  title,
  references,
  onNavigateToNode
}: {
  title: string;
  references: NodeReference[];
  onNavigateToNode: (nodeId: string, edgeType?: string) => void;
}) {
  return (
    <section className="metadata-section">
      <div className="filter-title">{title}</div>
      {references.length > 0 ? (
        <div className="metadata-chips">
          {references.slice(0, 16).map((reference) => (
            <button
              className="metadata-chip"
              disabled={!reference.nodeId}
              key={reference.id}
              onClick={() => {
                if (reference.nodeId) {
                  onNavigateToNode(reference.nodeId, reference.edgeType);
                }
              }}
              title={reference.nodeId ? `Open ${reference.label}` : reference.meta}
              type="button"
            >
              {reference.label}
            </button>
          ))}
          {references.length > 16 ? <span className="metadata-chip">+{references.length - 16}</span> : null}
        </div>
      ) : (
        <span className="muted small-text">None</span>
      )}
    </section>
  );
}

function buildEdgeReferences(
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

function buildResolvedMetadataValues(edges: CodeEdge[], edgeType: string, metadataKey: string): Set<string> {
  return new Set(
    edges
      .filter((edge) => edge.type === edgeType)
      .map((edge) => formatUnknown(edge.metadata[metadataKey]))
      .filter(Boolean)
  );
}

function buildUnresolvedReferences(
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

function RawMetadata({ metadata }: { metadata: Record<string, unknown> }) {
  const entries = Object.entries(metadata).filter(
    ([key]) => key !== "calls" && key !== "imports" && key !== "absolute_path"
  );
  if (entries.length === 0) {
    return null;
  }

  return (
    <section className="metadata-section">
      <div className="filter-title">Metadata</div>
      <dl className="metadata-list">
        {entries.slice(0, 10).map(([key, value]) => (
          <DetailItem key={key} label={key} value={formatUnknown(value)} />
        ))}
      </dl>
    </section>
  );
}
