import { useMemo } from "react";

import type { CodeEdge, CodeNode, GraphResponse } from "../api/client";
import {
  collectEdgeMetadata,
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
  containment
}: {
  visualData: VisualNodeData | null;
  node: CodeNode | null;
  edges: CodeEdge[];
  graph: GraphResponse | null;
  containment: ContainmentIndex;
}) {
  const rawNodeIds = visualData?.rawNodeIds ?? (node ? [node.id] : []);
  const visualStats = useMemo(
    () => (graph ? computeStatsForNodeIds(rawNodeIds, graph.edges) : { incoming: 0, outgoing: 0, calls: 0, imports: 0 }),
    [graph, rawNodeIds]
  );
  const imports = useMemo(() => collectEdgeMetadata(edges, "imports", "import"), [edges]);
  const calls = useMemo(() => {
    const metadataCalls = listFromUnknown(node?.metadata.calls);
    const edgeCalls = collectEdgeMetadata(edges, "calls", "call");
    return [...new Set([...metadataCalls, ...edgeCalls])];
  }, [edges, node?.metadata.calls]);

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

  return (
    <aside className="node-details">
      <div className="detail-heading">
        <span className="node-type-pill">{detailNode.type}</span>
        <h3>{detailNode.name}</h3>
      </div>

      <dl className="detail-list">
        <DetailItem label="File" value={detailNode.file_path || "External or repository scope"} />
        <DetailItem label="Lines" value={formatLineRange(detailNode)} />
        <DetailItem label="Language" value={detailNode.language || "Unknown"} />
        <DetailItem label="Edges" value={`${visualStats.incoming} in / ${visualStats.outgoing} out`} />
        {descendantCount > 0 ? <DetailItem label="Symbols" value={`${descendantCount}`} /> : null}
        {detailNode.symbol_id ? <DetailItem label="Symbol" value={detailNode.symbol_id} /> : null}
      </dl>

      <MetadataSection title="Imports" values={imports} />
      <MetadataSection title="Calls" values={calls} />
      <RawMetadata metadata={detailNode.metadata} />

      {graph ? (
        <div className="adjacent-list">
          <div className="filter-title">Adjacent edges</div>
          {edges.slice(0, 8).map((edge) => (
            <div className="adjacent-edge" key={edge.id}>
              <span>{edge.type}</span>
              <small>{edge.source === detailNode.id ? "outgoing" : "incoming"}</small>
            </div>
          ))}
          {edges.length > 8 ? <div className="muted small-text">+{edges.length - 8} more</div> : null}
        </div>
      ) : null}
    </aside>
  );
}

function DetailItem({ label, value }: { label: string; value: string }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </>
  );
}

function MetadataSection({ title, values }: { title: string; values: string[] }) {
  return (
    <section className="metadata-section">
      <div className="filter-title">{title}</div>
      {values.length > 0 ? (
        <div className="metadata-chips">
          {values.slice(0, 16).map((value) => (
            <span className="metadata-chip" key={value}>
              {value}
            </span>
          ))}
          {values.length > 16 ? <span className="metadata-chip">+{values.length - 16}</span> : null}
        </div>
      ) : (
        <span className="muted small-text">None</span>
      )}
    </section>
  );
}

function RawMetadata({ metadata }: { metadata: Record<string, unknown> }) {
  const entries = Object.entries(metadata).filter(([key]) => key !== "calls" && key !== "imports");
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
