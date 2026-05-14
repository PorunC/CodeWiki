import { useMemo } from "react";

import type { CodeEdge, CodeNode, GraphResponse } from "../api/types";
import {
  fileDisplayName,
  computeStatsForNodeIds,
  formatLineRange,
  getPrimaryNode,
  isFileLikeNode,
  listFromUnknown,
  type ContainmentIndex,
  type VisualNodeData
} from "./graphModel";
import { DetailItem } from "./nodeDetails/DetailItem";
import {
  buildEdgeReferences,
  buildResolvedMetadataValues,
  buildUnresolvedReferences
} from "./nodeDetails/model";
import { RawMetadata } from "./nodeDetails/RawMetadata";
import { ReferenceSection } from "./nodeDetails/ReferenceSection";

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

  const isFileLike = isFileLikeNode(detailNode);
  const descendantCount = isFileLike ? containment.descendantsByFile.get(detailNode.id)?.length ?? 0 : 0;
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
  const references = [
    ...buildEdgeReferences(edges, "references", "reference", selectedRawIds, nodeById),
    ...buildUnresolvedReferences(
      "references",
      listFromUnknown(detailNode.metadata.references),
      buildResolvedMetadataValues(edges, "references", "reference")
    )
  ];
  const implementsReferences = buildEdgeReferences(edges, "implements", "interface", selectedRawIds, nodeById);
  const configUses = buildEdgeReferences(edges, "uses_config", "imports", selectedRawIds, nodeById);

  return (
    <aside className="node-details">
      <div className="detail-heading">
        <span className="node-type-pill">{detailNode.type}</span>
        <h3>{isFileLike ? fileDisplayName(detailNode) : detailNode.name}</h3>
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
      <ReferenceSection title="Implements" references={implementsReferences} onNavigateToNode={onNavigateToNode} />
      <ReferenceSection title="References" references={references} onNavigateToNode={onNavigateToNode} />
      <ReferenceSection title="Config" references={configUses} onNavigateToNode={onNavigateToNode} />
      <RawMetadata metadata={detailNode.metadata} />
    </aside>
  );
}
