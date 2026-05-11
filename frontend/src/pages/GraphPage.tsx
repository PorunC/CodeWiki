import dagre from "@dagrejs/dagre";
import {
  Background,
  BackgroundVariant,
  Controls,
  MarkerType,
  MiniMap,
  Position,
  ReactFlow,
  type Edge,
  type Node
} from "@xyflow/react";
import { RefreshCcw } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  getRepoGraph,
  getRepos,
  type CodeEdge,
  type CodeNode,
  type GraphResponse,
  type RepoSummary
} from "../api/client";

const NODE_WIDTH = 210;
const NODE_HEIGHT = 66;

type FlowNode = Node<{ label: string; codeNode: CodeNode }>;
type FlowEdge = Edge<{ codeEdge: CodeEdge }>;

export function GraphPage() {
  const [repos, setRepos] = useState<RepoSummary[]>([]);
  const [selectedRepoId, setSelectedRepoId] = useState("");
  const [graph, setGraph] = useState<GraphResponse | null>(null);
  const [repoLoading, setRepoLoading] = useState(true);
  const [graphLoading, setGraphLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedNodeTypes, setSelectedNodeTypes] = useState<Set<string>>(new Set());
  const [selectedEdgeTypes, setSelectedEdgeTypes] = useState<Set<string>>(new Set());
  const [showInferredCalls, setShowInferredCalls] = useState(true);
  const [refreshNonce, setRefreshNonce] = useState(0);

  useEffect(() => {
    let cancelled = false;

    setRepoLoading(true);
    setError(null);
    getRepos()
      .then((repoList) => {
        if (cancelled) {
          return;
        }
        setRepos(repoList);
        setSelectedRepoId((current) => current || repoList[0]?.id || "");
      })
      .catch((apiError: unknown) => {
        if (!cancelled) {
          setError(apiError instanceof Error ? apiError.message : "Failed to load repositories");
        }
      })
      .finally(() => {
        if (!cancelled) {
          setRepoLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!selectedRepoId) {
      setGraph(null);
      setSelectedNodeId(null);
      return;
    }

    let cancelled = false;
    setGraphLoading(true);
    setError(null);
    getRepoGraph(selectedRepoId)
      .then((repoGraph) => {
        if (cancelled) {
          return;
        }
        setGraph(repoGraph);
        setSelectedNodeTypes(new Set(repoGraph.nodes.map((node) => node.type)));
        setSelectedEdgeTypes(new Set(repoGraph.edges.map((edge) => edge.type)));
        setSelectedNodeId(repoGraph.nodes[0]?.id ?? null);
      })
      .catch((apiError: unknown) => {
        if (!cancelled) {
          setGraph(null);
          setSelectedNodeId(null);
          setError(apiError instanceof Error ? apiError.message : "Failed to load repository graph");
        }
      })
      .finally(() => {
        if (!cancelled) {
          setGraphLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [refreshNonce, selectedRepoId]);

  const selectedRepo = useMemo(
    () => repos.find((repo) => repo.id === selectedRepoId) ?? null,
    [repos, selectedRepoId]
  );

  const nodeTypes = useMemo(() => collectTypes(graph?.nodes ?? []), [graph?.nodes]);
  const edgeTypes = useMemo(() => collectTypes(graph?.edges ?? []), [graph?.edges]);

  const visibleGraph = useMemo(() => {
    if (!graph) {
      return { nodes: [] as CodeNode[], edges: [] as CodeEdge[] };
    }

    const nodes = graph.nodes.filter((node) => selectedNodeTypes.has(node.type));
    const visibleNodeIds = new Set(nodes.map((node) => node.id));
    const edges = graph.edges.filter((edge) => {
      if (!selectedEdgeTypes.has(edge.type)) {
        return false;
      }
      if (!showInferredCalls && edge.type === "calls" && edge.is_inferred) {
        return false;
      }
      return visibleNodeIds.has(edge.source) && visibleNodeIds.has(edge.target);
    });

    return { nodes, edges };
  }, [graph, selectedEdgeTypes, selectedNodeTypes, showInferredCalls]);

  const flowNodes = useMemo(
    () => layoutNodes(visibleGraph.nodes, visibleGraph.edges, selectedNodeId),
    [selectedNodeId, visibleGraph.edges, visibleGraph.nodes]
  );

  const flowEdges = useMemo(
    () => visibleGraph.edges.map((edge) => toFlowEdge(edge)),
    [visibleGraph.edges]
  );

  useEffect(() => {
    if (!selectedNodeId) {
      return;
    }
    if (!visibleGraph.nodes.some((node) => node.id === selectedNodeId)) {
      setSelectedNodeId(visibleGraph.nodes[0]?.id ?? null);
    }
  }, [selectedNodeId, visibleGraph.nodes]);

  const selectedNode = useMemo(
    () => graph?.nodes.find((node) => node.id === selectedNodeId) ?? null,
    [graph?.nodes, selectedNodeId]
  );

  const selectedNodeEdges = useMemo(
    () =>
      graph?.edges.filter(
        (edge) => edge.source === selectedNodeId || edge.target === selectedNodeId
      ) ?? [],
    [graph?.edges, selectedNodeId]
  );

  const toggleNodeType = useCallback((type: string) => {
    setSelectedNodeTypes((current) => toggleSetValue(current, type));
  }, []);

  const toggleEdgeType = useCallback((type: string) => {
    setSelectedEdgeTypes((current) => toggleSetValue(current, type));
  }, []);

  const resetFilters = useCallback(() => {
    setSelectedNodeTypes(new Set(nodeTypes));
    setSelectedEdgeTypes(new Set(edgeTypes));
    setShowInferredCalls(true);
  }, [edgeTypes, nodeTypes]);

  const isLoading = repoLoading || graphLoading;

  return (
    <section id="graph" className="graph-panel">
      <header className="graph-header">
        <div>
          <span className="eyebrow">Graph</span>
          <h1>Code Structure</h1>
        </div>
        <button
          className="icon-button"
          type="button"
          onClick={() => setRefreshNonce((nonce) => nonce + 1)}
          disabled={!selectedRepoId || graphLoading}
          title="Refresh graph"
          aria-label="Refresh graph"
        >
          <RefreshCcw size={16} />
        </button>
      </header>

      <div className="graph-toolbar">
        <label className="field">
          <span>Repository</span>
          <select
            value={selectedRepoId}
            onChange={(event) => setSelectedRepoId(event.target.value)}
            disabled={repoLoading || repos.length === 0}
          >
            {repos.map((repo) => (
              <option key={repo.id} value={repo.id}>
                {repo.name}
              </option>
            ))}
          </select>
        </label>
        {selectedRepo ? <span className="repo-path">{selectedRepo.path}</span> : null}
        <div className="graph-counts" aria-live="polite">
          {graph
            ? `${visibleGraph.nodes.length}/${graph.nodes.length} nodes / ${visibleGraph.edges.length}/${graph.edges.length} edges`
            : "No graph loaded"}
        </div>
      </div>

      {error ? <div className="state-banner error-banner">{error}</div> : null}
      {!isLoading && repos.length === 0 ? (
        <div className="state-banner">No repositories registered yet.</div>
      ) : null}

      <div className="graph-workspace">
        <aside className="graph-filters">
          <FilterGroup
            title="Node types"
            values={nodeTypes}
            selectedValues={selectedNodeTypes}
            onToggle={toggleNodeType}
          />
          <FilterGroup
            title="Edge types"
            values={edgeTypes}
            selectedValues={selectedEdgeTypes}
            onToggle={toggleEdgeType}
          />
          <label className="check-row">
            <input
              type="checkbox"
              checked={showInferredCalls}
              onChange={(event) => setShowInferredCalls(event.target.checked)}
            />
            <span>Inferred calls</span>
          </label>
          <button className="secondary-button" type="button" onClick={resetFilters} disabled={!graph}>
            Reset filters
          </button>
        </aside>

        <div className="flow-frame">
          {isLoading ? <div className="flow-state">Loading graph...</div> : null}
          {!isLoading && graph && flowNodes.length === 0 ? (
            <div className="flow-state">No nodes match the current filters.</div>
          ) : null}
          {!isLoading && graph && flowNodes.length > 0 ? (
            <ReactFlow
              key={`${selectedRepoId}:${filterKey(selectedNodeTypes)}:${filterKey(selectedEdgeTypes)}:${showInferredCalls}`}
              nodes={flowNodes}
              edges={flowEdges}
              fitView
              fitViewOptions={{ padding: 0.2 }}
              minZoom={0.05}
              maxZoom={2}
              onNodeClick={(_, node) => setSelectedNodeId(node.id)}
              proOptions={{ hideAttribution: true }}
            >
              <Background
                variant={BackgroundVariant.Dots}
                gap={22}
                size={1}
                color="rgba(212, 165, 116, 0.14)"
              />
              <Controls />
              <MiniMap
                maskColor="rgba(8, 9, 10, 0.72)"
                nodeColor={(node) => {
                  const codeNode = (node.data as { codeNode?: CodeNode }).codeNode;
                  return nodeTone(codeNode?.type ?? "").border;
                }}
                pannable
                zoomable
              />
            </ReactFlow>
          ) : null}
        </div>

        <NodeDetails node={selectedNode} edges={selectedNodeEdges} graph={graph} />
      </div>
    </section>
  );
}

function FilterGroup({
  title,
  values,
  selectedValues,
  onToggle
}: {
  title: string;
  values: string[];
  selectedValues: Set<string>;
  onToggle: (value: string) => void;
}) {
  return (
    <div className="filter-group">
      <div className="filter-title">{title}</div>
      <div className="filter-options">
        {values.length === 0 ? <span className="muted small-text">None</span> : null}
        {values.map((value) => (
          <label className="check-row" key={value}>
            <input
              type="checkbox"
              checked={selectedValues.has(value)}
              onChange={() => onToggle(value)}
            />
            <span>{value}</span>
          </label>
        ))}
      </div>
    </div>
  );
}

function NodeDetails({
  node,
  edges,
  graph
}: {
  node: CodeNode | null;
  edges: CodeEdge[];
  graph: GraphResponse | null;
}) {
  const imports = useMemo(() => collectEdgeMetadata(edges, "imports", "import"), [edges]);
  const calls = useMemo(() => {
    const metadataCalls = listFromUnknown(node?.metadata.calls);
    const edgeCalls = collectEdgeMetadata(edges, "calls", "call");
    return [...new Set([...metadataCalls, ...edgeCalls])];
  }, [edges, node?.metadata.calls]);

  if (!node) {
    return (
      <aside className="node-details">
        <div className="detail-empty">Select a node to inspect it.</div>
      </aside>
    );
  }

  return (
    <aside className="node-details">
      <div className="detail-heading">
        <span className="node-type-pill">{node.type}</span>
        <h3>{node.name}</h3>
      </div>

      <dl className="detail-list">
        <DetailItem label="File" value={node.file_path || "External or repository scope"} />
        <DetailItem label="Lines" value={formatLineRange(node)} />
        <DetailItem label="Language" value={node.language || "Unknown"} />
        <DetailItem label="Edges" value={`${edges.length}`} />
        {node.symbol_id ? <DetailItem label="Symbol" value={node.symbol_id} /> : null}
      </dl>

      <MetadataSection title="Imports" values={imports} />
      <MetadataSection title="Calls" values={calls} />
      <RawMetadata metadata={node.metadata} />

      {graph ? (
        <div className="adjacent-list">
          <div className="filter-title">Adjacent edges</div>
          {edges.slice(0, 8).map((edge) => (
            <div className="adjacent-edge" key={edge.id}>
              <span>{edge.type}</span>
              <small>{edge.source === node.id ? "outgoing" : "incoming"}</small>
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
          {values.map((value) => (
            <span className="metadata-chip" key={value}>
              {value}
            </span>
          ))}
        </div>
      ) : (
        <span className="muted small-text">None</span>
      )}
    </section>
  );
}

function RawMetadata({ metadata }: { metadata: Record<string, unknown> }) {
  const entries = Object.entries(metadata).filter(([key]) => key !== "calls");
  if (entries.length === 0) {
    return null;
  }

  return (
    <section className="metadata-section">
      <div className="filter-title">Metadata</div>
      <dl className="metadata-list">
        {entries.map(([key, value]) => (
          <DetailItem key={key} label={key} value={formatUnknown(value)} />
        ))}
      </dl>
    </section>
  );
}

function layoutNodes(nodes: CodeNode[], edges: CodeEdge[], selectedNodeId: string | null): FlowNode[] {
  const dagreGraph = new dagre.graphlib.Graph();
  dagreGraph.setDefaultEdgeLabel(() => ({}));
  dagreGraph.setGraph({
    edgesep: 16,
    marginx: 24,
    marginy: 24,
    nodesep: 36,
    rankdir: "LR",
    ranksep: 96
  });

  nodes.forEach((node) => {
    dagreGraph.setNode(node.id, { width: NODE_WIDTH, height: NODE_HEIGHT });
  });
  edges.forEach((edge) => {
    dagreGraph.setEdge(edge.source, edge.target);
  });
  dagre.layout(dagreGraph);

  return nodes.map((node) => {
    const position = dagreGraph.node(node.id) as { x: number; y: number } | undefined;
    const tone = nodeTone(node.type);

    return {
      id: node.id,
      data: {
        label: node.name,
        codeNode: node
      },
      position: {
        x: (position?.x ?? 0) - NODE_WIDTH / 2,
        y: (position?.y ?? 0) - NODE_HEIGHT / 2
      },
      sourcePosition: Position.Right,
      targetPosition: Position.Left,
      style: {
        background: tone.background,
        border: `1px solid ${selectedNodeId === node.id ? "#d4a574" : tone.border}`,
        borderRadius: 8,
        boxShadow: selectedNodeId === node.id ? "0 0 0 3px rgba(212, 165, 116, 0.18)" : "none",
        color: "#f5f0eb",
        fontSize: 12,
        fontWeight: 700,
        minHeight: NODE_HEIGHT,
        padding: 10,
        width: NODE_WIDTH
      }
    };
  });
}

function toFlowEdge(edge: CodeEdge): FlowEdge {
  const tone = edgeTone(edge.type);

  return {
    id: edge.id,
    source: edge.source,
    target: edge.target,
    data: { codeEdge: edge },
    label: edge.type,
    labelBgBorderRadius: 4,
    labelBgPadding: [6, 3],
    labelBgStyle: { fill: "rgba(17, 17, 17, 0.92)" },
    labelStyle: { fill: "#a39787", fontSize: 10, fontWeight: 700 },
    markerEnd: { type: MarkerType.ArrowClosed },
    style: {
      stroke: tone,
      strokeDasharray: edge.is_inferred ? "6 4" : undefined,
      strokeWidth: edge.type === "calls" ? 2 : 1.5
    },
    type: "smoothstep"
  };
}

function collectTypes(items: Array<{ type: string }>): string[] {
  return [...new Set(items.map((item) => item.type))].sort((left, right) => left.localeCompare(right));
}

function toggleSetValue(values: Set<string>, value: string): Set<string> {
  const nextValues = new Set(values);
  if (nextValues.has(value)) {
    nextValues.delete(value);
  } else {
    nextValues.add(value);
  }
  return nextValues;
}

function filterKey(values: Set<string>): string {
  return [...values].sort().join("|");
}

function formatLineRange(node: CodeNode): string {
  if (node.start_line && node.end_line) {
    return `${node.start_line}-${node.end_line}`;
  }
  if (node.start_line) {
    return `${node.start_line}`;
  }
  return "Unknown";
}

function collectEdgeMetadata(edges: CodeEdge[], edgeType: string, metadataKey: string): string[] {
  return [
    ...new Set(
      edges
        .filter((edge) => edge.type === edgeType)
        .flatMap((edge) => listFromUnknown(edge.metadata[metadataKey]))
    )
  ];
}

function listFromUnknown(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.map((item) => formatUnknown(item)).filter(Boolean);
  }
  if (value === null || value === undefined || value === "") {
    return [];
  }
  return [formatUnknown(value)];
}

function formatUnknown(value: unknown): string {
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (value === null || value === undefined) {
    return "";
  }
  return JSON.stringify(value);
}

function nodeTone(type: string): { background: string; border: string } {
  switch (type) {
    case "repository":
      return { background: "#17251f", border: "#6fb07a" };
    case "directory":
      return { background: "#181a1d", border: "#5f6b73" };
    case "file":
      return { background: "#14202a", border: "#4a7c9b" };
    case "module":
      return { background: "#272015", border: "#c9a06c" };
    case "class":
      return { background: "#201a2a", border: "#8b6fb0" };
    case "function":
    case "method":
      return { background: "#14251d", border: "#5a9e6f" };
    default:
      return { background: "#171717", border: "#6b5f53" };
  }
}

function edgeTone(type: string): string {
  switch (type) {
    case "contains":
      return "rgba(212, 165, 116, 0.28)";
    case "imports":
      return "#c9a06c";
    case "calls":
      return "#5a9e6f";
    default:
      return "rgba(163, 151, 135, 0.45)";
  }
}
