import dagre from "@dagrejs/dagre";
import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
  type NodeTypes
} from "@xyflow/react";
import { EyeOff, FileCode2, Focus, FolderTree, Network, RefreshCcw } from "lucide-react";
import { memo, useCallback, useEffect, useMemo, useState } from "react";

import {
  getRepoGraph,
  getRepos,
  type CodeEdge,
  type CodeNode,
  type GraphResponse,
  type RepoSummary
} from "../api/client";

const FILE_NODE_WIDTH = 244;
const FILE_NODE_HEIGHT = 126;
const SYMBOL_NODE_WIDTH = 244;
const SYMBOL_NODE_HEIGHT = 112;
const GROUP_GAP_X = 112;
const GROUP_GAP_Y = 92;
const GROUP_PADDING_X = 24;
const GROUP_HEADER_HEIGHT = 72;
const GROUP_CHILD_GAP = 18;
const FILE_DETAIL_WIDTH = 700;
const MAX_PORTAL_NODES = 14;
const TARGET_HANDLE_ID = "target-left";
const SOURCE_HANDLE_ID = "source-right";

type GraphViewMode = "overview" | "file" | "focus";

type VisualNodeData = CodeVisualData | ContainerVisualData;

type FlowNode = Node<VisualNodeData, "code" | "container">;
type FlowEdge = Edge<VisualEdgeData>;

type VisualEdgeData = {
  edgeType: string;
  count: number;
  rawEdgeIds: string[];
  hasInferred: boolean;
};

type CodeVisualData = {
  kind: "code";
  label: string;
  nodeType: string;
  summary: string;
  pathLabel: string;
  lineLabel: string;
  countLabel?: string;
  statsLabel?: string;
  accentColor: string;
  codeNode: CodeNode;
  fileId?: string;
  rawNodeIds: string[];
  isSelected: boolean;
  isNeighbor: boolean;
  isFaded: boolean;
  isContained: boolean;
  isExternal: boolean;
};

type ContainerVisualData = {
  kind: "container";
  title: string;
  subtitle: string;
  containerType: "repository" | "directory" | "file" | "dependency" | "focus";
  pathLabel: string;
  countLabel: string;
  statsLabel: string;
  accentColor: string;
  fileId?: string;
  primaryNodeId?: string;
  rawNodeIds: string[];
  isSelected: boolean;
  isNeighbor: boolean;
  isFaded: boolean;
  isFocusedViaChild: boolean;
  isCompact: boolean;
};

type FilteredGraph = {
  nodes: CodeNode[];
  edges: CodeEdge[];
  nodeIds: Set<string>;
};

type ContainmentIndex = {
  nodeById: Map<string, CodeNode>;
  childrenByParent: Map<string, string[]>;
  parentByChild: Map<string, string>;
  fileByNode: Map<string, string>;
  descendantsByFile: Map<string, string[]>;
};

type FileGroup = {
  id: string;
  name: string;
  pathLabel: string;
  files: CodeNode[];
  width: number;
  height: number;
  childPositions: Map<string, { x: number; y: number }>;
};

type EdgeBucket = {
  id: string;
  source: string;
  target: string;
  type: string;
  count: number;
  rawEdgeIds: string[];
  hasInferred: boolean;
};

type NodeStats = {
  incoming: number;
  outgoing: number;
  calls: number;
  imports: number;
};

type FileDetailSymbolSlot = {
  node: CodeNode;
  x: number;
  y: number;
  width: number;
  height: number;
  label: string;
  pathLabel: string;
  summary: string;
  countLabel: string;
};

const flowNodeTypes: NodeTypes = {
  code: memo(CodeFlowNode),
  container: memo(ContainerFlowNode)
};

export function GraphPage() {
  const [repos, setRepos] = useState<RepoSummary[]>([]);
  const [selectedRepoId, setSelectedRepoId] = useState("");
  const [graph, setGraph] = useState<GraphResponse | null>(null);
  const [repoLoading, setRepoLoading] = useState(true);
  const [graphLoading, setGraphLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<GraphViewMode>("overview");
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedVisualId, setSelectedVisualId] = useState<string | null>(null);
  const [selectedFileId, setSelectedFileId] = useState<string | null>(null);
  const [selectedNodeTypes, setSelectedNodeTypes] = useState<Set<string>>(new Set());
  const [selectedEdgeTypes, setSelectedEdgeTypes] = useState<Set<string>>(new Set());
  const [showInferredCalls, setShowInferredCalls] = useState(true);
  const [hiddenVisualIds, setHiddenVisualIds] = useState<Set<string>>(new Set());
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
      setSelectedVisualId(null);
      setSelectedFileId(null);
      setHiddenVisualIds(new Set());
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
        const firstFile = repoGraph.nodes.find((node) => node.type === "file") ?? repoGraph.nodes[0] ?? null;

        setGraph(repoGraph);
        setSelectedNodeTypes(new Set(repoGraph.nodes.map((node) => node.type)));
        setSelectedEdgeTypes(new Set(repoGraph.edges.map((edge) => edge.type)));
        setSelectedNodeId(firstFile?.id ?? null);
        setSelectedVisualId(null);
        setSelectedFileId(firstFile?.type === "file" ? firstFile.id : null);
        setHiddenVisualIds(new Set());
        setViewMode("overview");
      })
      .catch((apiError: unknown) => {
        if (!cancelled) {
          setGraph(null);
          setSelectedNodeId(null);
          setSelectedVisualId(null);
          setSelectedFileId(null);
          setHiddenVisualIds(new Set());
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

  const containment = useMemo(() => deriveContainment(graph), [graph]);
  const nodeTypes = useMemo(() => collectTypes(graph?.nodes ?? []), [graph?.nodes]);
  const edgeTypes = useMemo(() => collectTypes(graph?.edges ?? []), [graph?.edges]);

  const filteredGraph = useMemo(
    () => filterRawGraph(graph, selectedNodeTypes, selectedEdgeTypes, showInferredCalls),
    [graph, selectedEdgeTypes, selectedNodeTypes, showInferredCalls]
  );

  useEffect(() => {
    if (!graph || viewMode !== "file" || selectedFileId) {
      return;
    }
    const nextFile = graph.nodes.find((node) => node.type === "file");
    if (nextFile) {
      setSelectedFileId(nextFile.id);
      setSelectedNodeId(nextFile.id);
      setSelectedVisualId(`file-detail:${nextFile.id}`);
    }
  }, [graph, selectedFileId, viewMode]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") {
        return;
      }
      setSelectedVisualId(null);
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  const baseVisualGraph = useMemo(() => {
    if (!graph) {
      return { nodes: [] as FlowNode[], edges: [] as FlowEdge[] };
    }

    if (viewMode === "file") {
      return buildFileDetailGraph(graph, filteredGraph, containment, selectedFileId, selectedNodeId, selectedVisualId);
    }

    if (viewMode === "focus") {
      return buildFocusGraph(graph, filteredGraph, containment, selectedNodeId, selectedVisualId);
    }

    return buildOverviewGraph(graph, filteredGraph, containment, selectedVisualId);
  }, [containment, filteredGraph, graph, selectedFileId, selectedNodeId, selectedVisualId, viewMode]);

  const visualGraph = useMemo(
    () => pruneHiddenVisualGraph(baseVisualGraph, hiddenVisualIds),
    [baseVisualGraph, hiddenVisualIds]
  );

  const selectedVisualData = useMemo(
    () => visualGraph.nodes.find((node) => node.id === selectedVisualId)?.data ?? null,
    [selectedVisualId, visualGraph.nodes]
  );

  const selectedNode = useMemo(
    () => graph?.nodes.find((node) => node.id === selectedNodeId) ?? null,
    [graph?.nodes, selectedNodeId]
  );

  const selectedDetailRawIds = useMemo(
    () => selectedVisualData?.rawNodeIds ?? (selectedNodeId ? [selectedNodeId] : []),
    [selectedNodeId, selectedVisualData]
  );

  const selectedNodeEdges = useMemo(
    () => {
      const rawIds = new Set(selectedDetailRawIds);
      return graph?.edges.filter((edge) => rawIds.has(edge.source) || rawIds.has(edge.target)) ?? [];
    },
    [graph?.edges, selectedDetailRawIds]
  );

  const graphStats = useMemo(
    () => summarizeVisualGraph(graph, filteredGraph, visualGraph),
    [filteredGraph, graph, visualGraph]
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

  const openFileDetail = useCallback((fileId: string) => {
    setSelectedVisualId(`file-detail:${fileId}`);
    setSelectedNodeId(fileId);
    setSelectedFileId(fileId);
    setViewMode("file");
  }, []);

  useEffect(() => {
    const handleOpenFileDetail = (event: Event) => {
      const fileId = (event as CustomEvent<{ fileId?: string }>).detail?.fileId;
      if (fileId) {
        openFileDetail(fileId);
      }
    };

    window.addEventListener("codewiki:open-file-detail", handleOpenFileDetail);
    return () => window.removeEventListener("codewiki:open-file-detail", handleOpenFileDetail);
  }, [openFileDetail]);

  useEffect(() => {
    const handleHideNode = (event: Event) => {
      const nodeId = (event as CustomEvent<{ nodeId?: string }>).detail?.nodeId;
      if (!nodeId) {
        return;
      }
      setHiddenVisualIds((current) => {
        const next = new Set(current);
        next.add(nodeId);
        return next;
      });
      setSelectedVisualId((current) => (current === nodeId ? null : current));
      setSelectedNodeId((current) => (current === nodeId ? null : current));
    };

    window.addEventListener("codewiki:hide-visual-node", handleHideNode);
    return () => window.removeEventListener("codewiki:hide-visual-node", handleHideNode);
  }, []);

  const handleNodeClick = useCallback(
    (_: React.MouseEvent, node: FlowNode) => {
      const data = node.data;
      const primaryNodeId =
        data.kind === "container" ? data.primaryNodeId ?? null : data.codeNode.id;
      setSelectedVisualId(node.id);
      setSelectedNodeId(primaryNodeId);

      if (data.fileId && viewMode !== "file") {
        setSelectedFileId(data.fileId);
      }
    },
    [viewMode]
  );

  const handleNodeDoubleClick = useCallback(
    (_: React.MouseEvent, node: FlowNode) => {
      const data = node.data;
      if (data.kind === "code" && data.nodeType === "file" && data.fileId) {
        openFileDetail(data.fileId);
      }
    },
    [openFileDetail]
  );

  const selectMode = useCallback(
    (mode: GraphViewMode) => {
      setViewMode(mode);
      if (mode === "file" && selectedFileId) {
        setSelectedVisualId(`file-detail:${selectedFileId}`);
        setSelectedNodeId(selectedFileId);
      }
      if (mode === "overview" && selectedFileId) {
        setSelectedVisualId(selectedFileId);
        setSelectedNodeId(selectedFileId);
      }
      if (mode === "focus" && selectedNodeId) {
        setSelectedVisualId(selectedNodeId);
      }
    },
    [selectedFileId, selectedNodeId]
  );

  const isLoading = repoLoading || graphLoading;
  const layoutKey = viewMode === "file" ? selectedFileId ?? "none" : "stable";
  const flowKey = `${selectedRepoId}:${viewMode}:${layoutKey}:${filterKey(selectedNodeTypes)}:${filterKey(
    selectedEdgeTypes
  )}:${showInferredCalls}`;

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
        <div className="toolbar-actions">
          <div className="view-switcher" aria-label="Graph view mode">
            <ModeButton
              active={viewMode === "overview"}
              label="Overview"
              title="Overview"
              icon={<Network size={14} />}
              onClick={() => selectMode("overview")}
            />
            <ModeButton
              active={viewMode === "file"}
              label="File"
              title="File detail"
              icon={<FileCode2 size={14} />}
              onClick={() => selectMode("file")}
              disabled={!selectedFileId}
            />
            <ModeButton
              active={viewMode === "focus"}
              label="Focus"
              title="Focus neighborhood"
              icon={<Focus size={14} />}
              onClick={() => selectMode("focus")}
              disabled={!selectedNodeId}
            />
          </div>
          <div className="graph-counts" aria-live="polite">
            {graphStats}
          </div>
        </div>
      </div>

      {error ? <div className="state-banner error-banner">{error}</div> : null}
      {!isLoading && repos.length === 0 ? (
        <div className="state-banner">No repositories registered yet.</div>
      ) : null}

      <div className="graph-workspace">
        <aside className="graph-filters">
          <div className="graph-insight">
            <FolderTree size={16} />
            <span>{modeHint(viewMode)}</span>
          </div>
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
          {hiddenVisualIds.size > 0 ? (
            <button className="secondary-button" type="button" onClick={() => setHiddenVisualIds(new Set())}>
              Show hidden nodes ({hiddenVisualIds.size})
            </button>
          ) : null}
        </aside>

        <div className="flow-frame">
          {isLoading ? <div className="flow-state">Loading graph...</div> : null}
          {!isLoading && graph && visualGraph.nodes.length === 0 ? (
            <div className="flow-state">No nodes match the current filters.</div>
          ) : null}
          {!isLoading && graph && visualGraph.nodes.length > 0 ? (
            <ReactFlow
              key={flowKey}
              nodes={visualGraph.nodes}
              edges={visualGraph.edges}
              nodeTypes={flowNodeTypes}
              fitView
              fitViewOptions={{ padding: 0.18 }}
              minZoom={0.04}
              maxZoom={2}
              nodesDraggable={false}
              onNodeClick={handleNodeClick}
              onNodeDoubleClick={handleNodeDoubleClick}
              zoomOnDoubleClick={false}
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
                nodeColor={(node) => miniMapColor(node as FlowNode)}
                pannable
                zoomable
              />
            </ReactFlow>
          ) : null}
        </div>

        <NodeDetails
          visualData={selectedVisualData}
          node={selectedNode}
          edges={selectedNodeEdges}
          graph={graph}
          containment={containment}
        />
      </div>
    </section>
  );
}

function ModeButton({
  active,
  disabled,
  icon,
  label,
  title,
  onClick
}: {
  active: boolean;
  disabled?: boolean;
  icon: React.ReactNode;
  label: string;
  title: string;
  onClick: () => void;
}) {
  return (
    <button
      className={`mode-button${active ? " is-active" : ""}`}
      type="button"
      title={title}
      aria-pressed={active}
      onClick={onClick}
      disabled={disabled}
    >
      {icon}
      <span>{label}</span>
    </button>
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

function CodeFlowNode({ id, data }: NodeProps<Node<CodeVisualData, "code">>) {
  const className = [
    "code-node-card",
    data.isContained ? "is-contained" : "",
    data.isExternal ? "is-external" : "",
    data.isSelected ? "is-selected" : "",
    data.isNeighbor ? "is-neighbor" : "",
    data.isFaded ? "is-faded" : ""
  ]
    .filter(Boolean)
    .join(" ");

  const handleDoubleClick = (event: React.MouseEvent<HTMLDivElement>) => {
    if (data.nodeType !== "file" || !data.fileId) {
      return;
    }
    event.stopPropagation();
    window.dispatchEvent(
      new CustomEvent("codewiki:open-file-detail", {
        detail: { fileId: data.fileId }
      })
    );
  };

  const handleHideClick = (event: React.MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation();
    window.dispatchEvent(
      new CustomEvent("codewiki:hide-visual-node", {
        detail: { nodeId: id }
      })
    );
  };

  return (
    <div className={className} title={data.label} onDoubleClick={handleDoubleClick}>
      <div className="code-node-accent" style={{ background: data.accentColor }} />
      <Handle id={TARGET_HANDLE_ID} type="target" position={Position.Left} className="code-node-handle" />
      <Handle id={SOURCE_HANDLE_ID} type="source" position={Position.Right} className="code-node-handle" />
      <div className="code-node-body">
        <div className="code-node-topline">
          <span className="code-node-type" style={{ color: data.accentColor }}>
            {data.nodeType}
          </span>
          {data.countLabel ? <span className="code-node-count">{data.countLabel}</span> : null}
        </div>
        <div className="code-node-title">{data.label}</div>
        <div className="code-node-summary">{data.summary}</div>
        <div className="code-node-meta">
          <span>{data.pathLabel}</span>
          <span>{data.lineLabel}</span>
        </div>
      </div>
      <div className="code-node-stats">
        <span>{data.statsLabel || "No visible edges"}</span>
      </div>
      <button
        className="node-hide-button nodrag nopan"
        type="button"
        title="Hide node"
        aria-label={`Hide ${data.label}`}
        onPointerDown={(event) => event.stopPropagation()}
        onClick={handleHideClick}
      >
        <EyeOff size={12} />
      </button>
    </div>
  );
}

function ContainerFlowNode({ id, data, width, height }: NodeProps<Node<ContainerVisualData, "container">>) {
  const className = [
    "code-container-node",
    data.isCompact ? "is-compact" : "",
    data.containerType === "dependency" ? "is-dependency" : "",
    data.isSelected ? "is-selected" : "",
    data.isNeighbor ? "is-neighbor" : "",
    data.isFaded ? "is-faded" : "",
    data.isFocusedViaChild ? "is-focused-via-child" : ""
  ]
    .filter(Boolean)
    .join(" ");

  const handleHideClick = (event: React.MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation();
    window.dispatchEvent(
      new CustomEvent("codewiki:hide-visual-node", {
        detail: { nodeId: id }
      })
    );
  };

  return (
    <div className={className} style={{ borderColor: data.accentColor, width, height }}>
      <Handle id={TARGET_HANDLE_ID} type="target" position={Position.Left} className="code-node-handle" />
      <Handle id={SOURCE_HANDLE_ID} type="source" position={Position.Right} className="code-node-handle" />
      <div className="code-container-header">
        <div>
          <span className="code-container-kind" style={{ color: data.accentColor }}>
            {data.subtitle}
          </span>
          <div className="code-container-title">{data.title}</div>
        </div>
        <span className="code-container-count">{data.countLabel}</span>
      </div>
      <div className="code-container-path">{data.pathLabel}</div>
      <div className="code-container-body">
        <span>{data.statsLabel}</span>
      </div>
      <button
        className="node-hide-button nodrag nopan"
        type="button"
        title="Hide node"
        aria-label={`Hide ${data.title}`}
        onPointerDown={(event) => event.stopPropagation()}
        onClick={handleHideClick}
      >
        <EyeOff size={12} />
      </button>
    </div>
  );
}

function NodeDetails({
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

function buildOverviewGraph(
  graph: GraphResponse,
  filtered: FilteredGraph,
  containment: ContainmentIndex,
  selectedVisualId: string | null
): { nodes: FlowNode[]; edges: FlowEdge[] } {
  const fileIds = collectOverviewFileIds(filtered.nodes, filtered.edges, containment);
  const fileNodes = [...fileIds]
    .map((id) => containment.nodeById.get(id))
    .filter((node): node is CodeNode => Boolean(node))
    .sort(compareByPath);
  const groups = deriveFileGroups(fileNodes);
  const fileToGroup = new Map<string, string>();

  groups.forEach((group) => {
    group.files.forEach((file) => fileToGroup.set(file.id, group.id));
  });

  const dependencyNodeId = "dependency:external";
  const rawToVisualId = new Map<string, string>();

  graph.nodes.forEach((node) => {
    if (node.type === "module") {
      rawToVisualId.set(node.id, dependencyNodeId);
      return;
    }

    const fileId = containment.fileByNode.get(node.id);
    if (fileId && fileIds.has(fileId)) {
      rawToVisualId.set(node.id, fileId);
    }
  });

  const edgeBuckets = aggregateEdges(filtered.edges, rawToVisualId, {
    skipSelfEdges: true,
    skipTypes: new Set(["contains"])
  });

  const groupEdgeBuckets = aggregateEdges(filtered.edges, new Map([...rawToVisualId].map(([rawId, visualId]) => {
    const groupId = visualId === dependencyNodeId ? dependencyNodeId : fileToGroup.get(visualId);
    return [rawId, groupId ?? visualId];
  })), {
    skipSelfEdges: true,
    skipTypes: new Set(["contains"])
  });

  const topLevelNodes = groups.map((group) => ({ id: group.id, width: group.width, height: group.height }));
  const hasDependencies = filtered.nodes.some((node) => node.type === "module") || edgeBuckets.some((edge) => edge.source === dependencyNodeId || edge.target === dependencyNodeId);

  if (hasDependencies) {
    topLevelNodes.push({ id: dependencyNodeId, width: 300, height: 190 });
  }

  const topLevelPositions = layoutBoxes(topLevelNodes, groupEdgeBuckets, "LR");
  const statsByRawNode = computeStatsByRawNode(graph.edges);
  const nodes: FlowNode[] = [];

  groups.forEach((group) => {
    const position = topLevelPositions.get(group.id) ?? { x: 0, y: 0 };
    const rawNodeIds = group.files.flatMap((file) => [file.id, ...(containment.descendantsByFile.get(file.id) ?? [])]);
    const groupStats = computeStatsForNodeIds(rawNodeIds, filtered.edges);

    nodes.push({
      id: group.id,
      type: "container",
      position,
      data: {
        kind: "container",
        title: group.name,
        subtitle: "folder container",
        containerType: "directory",
        pathLabel: group.pathLabel,
        countLabel: `${group.files.length}`,
        statsLabel: `${groupStats.incoming} in / ${groupStats.outgoing} out`,
        accentColor: nodeTone("directory").border,
        rawNodeIds,
        isSelected: false,
        isNeighbor: false,
        isFaded: false,
        isFocusedViaChild: false,
        isCompact: false
      },
      ...nodeSize(group.width, group.height),
      selectable: true,
      draggable: false
    });

    group.files.forEach((file) => {
      const childPosition = group.childPositions.get(file.id) ?? { x: GROUP_PADDING_X, y: GROUP_HEADER_HEIGHT };
      const descendants = containment.descendantsByFile.get(file.id) ?? [];
      const stats = computeStatsForNodeIds([file.id, ...descendants], filtered.edges);

      nodes.push({
        id: file.id,
        type: "code",
        parentId: group.id,
        extent: "parent",
        position: childPosition,
        data: toCodeVisualData(file, {
          containment,
          fileId: file.id,
          rawNodeIds: [file.id, ...descendants],
          summary: `${descendants.length} symbols in ${compactFilePath(file.file_path ?? file.name)}`,
          countLabel: `${descendants.length}`,
          statsLabel: `${stats.calls} calls / ${stats.imports} imports`,
          isContained: true,
          isExternal: false,
          stats: statsByRawNode.get(file.id)
        }),
        ...nodeSize(FILE_NODE_WIDTH, FILE_NODE_HEIGHT),
        selectable: true,
        draggable: false,
        zIndex: 5
      });
    });
  });

  if (hasDependencies) {
    const depPosition = topLevelPositions.get(dependencyNodeId) ?? { x: 0, y: 0 };
    const moduleIds = filtered.nodes.filter((node) => node.type === "module").map((node) => node.id);
    const depStats = computeStatsForNodeIds(moduleIds, filtered.edges);

    nodes.push({
      id: dependencyNodeId,
      type: "container",
      position: depPosition,
      data: {
        kind: "container",
        title: "External Dependencies",
        subtitle: "module container",
        containerType: "dependency",
        pathLabel: "imports collapsed by target module",
        countLabel: `${moduleIds.length}`,
        statsLabel: `${depStats.incoming} imports / ${depStats.outgoing} out`,
        accentColor: nodeTone("module").border,
        rawNodeIds: moduleIds,
        isSelected: false,
        isNeighbor: false,
        isFaded: false,
        isFocusedViaChild: false,
        isCompact: false
      },
      ...nodeSize(300, 190),
      selectable: true,
      draggable: false
    });
  }

  const edges = edgeBuckets.map((bucket) => toFlowEdge(bucket));
  return applyVisualState(nodes, edges, selectedVisualId, "overview");
}

function buildFileDetailGraph(
  graph: GraphResponse,
  filtered: FilteredGraph,
  containment: ContainmentIndex,
  selectedFileId: string | null,
  selectedNodeId: string | null,
  selectedVisualId: string | null
): { nodes: FlowNode[]; edges: FlowEdge[] } {
  const fileNode =
    (selectedFileId ? containment.nodeById.get(selectedFileId) : null) ??
    graph.nodes.find((node) => node.type === "file") ??
    null;

  if (!fileNode) {
    return { nodes: [], edges: [] };
  }

  const descendantIds = containment.descendantsByFile.get(fileNode.id) ?? [];
  const visibleSymbols = descendantIds
    .map((id) => containment.nodeById.get(id))
    .filter((node): node is CodeNode => Boolean(node))
    .filter((node) => filtered.nodeIds.has(node.id))
    .filter((node) => node.type === "class" || node.type === "function" || node.type === "method")
    .sort(compareBySourceOrder);
  const symbolSlots = layoutFileDetailSymbols(visibleSymbols, fileNode.id, containment);

  const fileContainerId = `file-detail:${fileNode.id}`;
  const fileHeight = Math.max(
    320,
    GROUP_HEADER_HEIGHT +
      38 +
      Math.max(0, ...symbolSlots.map((slot) => slot.y + slot.height - GROUP_HEADER_HEIGHT))
  );
  const stats = computeStatsForNodeIds([fileNode.id, ...descendantIds], filtered.edges);
  const nodes: FlowNode[] = [
    {
      id: fileContainerId,
      type: "container",
      position: { x: 0, y: 0 },
      data: {
        kind: "container",
        title: fileNode.name,
        subtitle: "file detail",
        containerType: "file",
        pathLabel: fileNode.file_path ?? fileNode.name,
        countLabel: `${visibleSymbols.length}`,
        statsLabel: `${stats.calls} calls / ${stats.imports} imports`,
        accentColor: nodeTone("file").border,
        fileId: fileNode.id,
        primaryNodeId: fileNode.id,
        rawNodeIds: [fileNode.id, ...descendantIds],
        isSelected: false,
        isNeighbor: false,
        isFaded: false,
        isFocusedViaChild: Boolean(selectedNodeId && selectedNodeId !== fileNode.id),
        isCompact: false
      },
      ...nodeSize(FILE_DETAIL_WIDTH, fileHeight),
      selectable: true,
      draggable: false
    }
  ];

  symbolSlots.forEach((slot) => {
    const node = slot.node;
    nodes.push({
      id: node.id,
      type: "code",
      parentId: fileContainerId,
      extent: "parent",
      position: {
        x: slot.x,
        y: slot.y
      },
      data: toCodeVisualData(node, {
        containment,
        label: slot.label,
        fileId: fileNode.id,
        rawNodeIds: [node.id],
        summary: slot.summary,
        countLabel: slot.countLabel,
        pathLabel: slot.pathLabel,
        stats: computeStatsByRawNode(graph.edges).get(node.id),
        isContained: true,
        isExternal: false
      }),
      ...nodeSize(slot.width, slot.height),
      selectable: true,
      draggable: false,
      zIndex: 6
    });
  });

  const internalSymbolIds = new Set(visibleSymbols.map((node) => node.id));
  const selectedSymbolId = selectedNodeId && internalSymbolIds.has(selectedNodeId) ? selectedNodeId : null;
  const internalEdges = selectedSymbolId
    ? filtered.edges.filter(
        (edge) =>
          edge.type !== "contains" &&
          (edge.source === selectedSymbolId || edge.target === selectedSymbolId) &&
          internalSymbolIds.has(edge.source) &&
          internalSymbolIds.has(edge.target)
      )
    : [];
  const rawToInternalVisual = new Map<string, string>(visibleSymbols.map((node) => [node.id, node.id]));
  const edges: FlowEdge[] = aggregateEdges(internalEdges, rawToInternalVisual, {
    skipSelfEdges: true
  }).map((bucket) => toFlowEdge(bucket));

  const portals = collectFilePortals(fileNode.id, selectedSymbolId, filtered.edges, containment, graph);
  const outgoing = portals.filter((portal) => portal.direction === "out").slice(0, MAX_PORTAL_NODES);
  const incoming = portals.filter((portal) => portal.direction === "in").slice(0, MAX_PORTAL_NODES);

  outgoing.forEach((portal, index) => {
    nodes.push(portalToNode(portal, { x: FILE_DETAIL_WIDTH + 150, y: 36 + index * 150 }, containment));
    edges.push(toFlowEdge(portal.bucket, selectedSymbolId ?? fileContainerId, portal.visualId));
  });

  incoming.forEach((portal, index) => {
    nodes.push(portalToNode(portal, { x: -FILE_NODE_WIDTH - 150, y: 36 + index * 150 }, containment));
    edges.push(toFlowEdge(portal.bucket, portal.visualId, selectedSymbolId ?? fileContainerId));
  });

  return applyVisualState(nodes, edges, selectedVisualId, "file");
}

function buildFocusGraph(
  graph: GraphResponse,
  filtered: FilteredGraph,
  containment: ContainmentIndex,
  selectedNodeId: string | null,
  selectedVisualId: string | null
): { nodes: FlowNode[]; edges: FlowEdge[] } {
  const focusNode = selectedNodeId ? containment.nodeById.get(selectedNodeId) : null;
  if (!focusNode || !filtered.nodeIds.has(focusNode.id)) {
    return buildOverviewGraph(graph, filtered, containment, selectedVisualId);
  }

  const relevantNodeIds = new Set<string>([focusNode.id]);
  const relevantEdges = filtered.edges.filter((edge) => {
    const isRelevant = edge.source === focusNode.id || edge.target === focusNode.id;
    if (isRelevant) {
      relevantNodeIds.add(edge.source);
      relevantNodeIds.add(edge.target);
    }
    return isRelevant;
  });

  const fileId = containment.fileByNode.get(focusNode.id);
  if (focusNode.type === "file") {
    for (const childId of containment.descendantsByFile.get(focusNode.id) ?? []) {
      if (filtered.nodeIds.has(childId)) {
        relevantNodeIds.add(childId);
      }
    }
  } else if (fileId) {
    relevantNodeIds.add(fileId);
  }

  const rawNodes = [...relevantNodeIds]
    .map((id) => containment.nodeById.get(id))
    .filter((node): node is CodeNode => Boolean(node))
    .sort(compareBySourceOrder);
  const rawNodeIds = new Set(rawNodes.map((node) => node.id));
  const rawEdges = filtered.edges.filter((edge) => rawNodeIds.has(edge.source) && rawNodeIds.has(edge.target));
  const positions = layoutBoxes(
    rawNodes.map((node) => ({
      id: node.id,
      width: node.type === "file" ? FILE_NODE_WIDTH : SYMBOL_NODE_WIDTH,
      height: node.type === "file" ? FILE_NODE_HEIGHT : SYMBOL_NODE_HEIGHT
    })),
    rawEdges.map((edge) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      type: edge.type,
      count: 1,
      rawEdgeIds: [edge.id],
      hasInferred: edge.is_inferred
    })),
    "LR"
  );
  const statsByRawNode = computeStatsByRawNode(graph.edges);

  const nodes: FlowNode[] = rawNodes.map((node) => ({
    id: node.id,
    type: "code",
    position: positions.get(node.id) ?? { x: 0, y: 0 },
    data: toCodeVisualData(node, {
      containment,
      fileId: containment.fileByNode.get(node.id),
      rawNodeIds: [node.id],
      summary: nodeSummary(node),
      countLabel: node.type === "file" ? `${containment.descendantsByFile.get(node.id)?.length ?? 0}` : formatLineRange(node),
      stats: statsByRawNode.get(node.id),
      isContained: false,
      isExternal: node.type === "module"
    }),
    ...nodeSize(
      node.type === "file" ? FILE_NODE_WIDTH : SYMBOL_NODE_WIDTH,
      node.type === "file" ? FILE_NODE_HEIGHT : SYMBOL_NODE_HEIGHT
    ),
    selectable: true,
    draggable: false
  }));

  const rawToVisual = new Map(rawNodes.map((node) => [node.id, node.id]));
  const edges = aggregateEdges(rawEdges, rawToVisual, { skipSelfEdges: true }).map((bucket) => toFlowEdge(bucket));

  return applyVisualState(nodes, edges, selectedVisualId, "focus");
}

function layoutFileDetailSymbols(
  symbols: CodeNode[],
  fileId: string,
  containment: ContainmentIndex
): FileDetailSymbolSlot[] {
  const slots: FileDetailSymbolSlot[] = [];
  const processed = new Set<string>();
  const visibleById = new Set(symbols.map((node) => node.id));
  const methodsByClass = new Map<string, CodeNode[]>();

  symbols.forEach((node) => {
    if (node.type !== "method") {
      return;
    }
    const classId = nearestAncestorOfType(node.id, "class", containment);
    if (!classId || !visibleById.has(classId)) {
      return;
    }
    const methods = methodsByClass.get(classId) ?? [];
    methods.push(node);
    methodsByClass.set(classId, methods);
  });

  methodsByClass.forEach((methods) => {
    methods.sort(compareBySourceOrder);
  });

  let y = GROUP_HEADER_HEIGHT + 26;
  const classX = 32;
  const methodX = 330;
  const methodGap = 12;
  const sectionGap = 22;

  symbols.forEach((node) => {
    if (processed.has(node.id)) {
      return;
    }

    if (node.type === "class") {
      const methods = methodsByClass.get(node.id) ?? [];
      const className = classDisplayName(node);
      const methodStackHeight =
        methods.length === 0 ? 0 : methods.length * SYMBOL_NODE_HEIGHT + (methods.length - 1) * methodGap;
      const sectionHeight = Math.max(SYMBOL_NODE_HEIGHT, methodStackHeight);

      slots.push({
        node,
        x: classX,
        y,
        width: SYMBOL_NODE_WIDTH,
        height: SYMBOL_NODE_HEIGHT,
        label: className,
        pathLabel: "class",
        summary: methods.length > 0 ? `${className} · ${methods.length} methods` : className,
        countLabel: formatLineRange(node)
      });
      processed.add(node.id);

      methods.forEach((method, index) => {
        slots.push({
          node: method,
          x: methodX,
          y: y + index * (SYMBOL_NODE_HEIGHT + methodGap),
          width: SYMBOL_NODE_WIDTH,
          height: SYMBOL_NODE_HEIGHT,
          label: methodDisplayName(method),
          pathLabel: className,
          summary: methodDisplayName(method),
          countLabel: formatLineRange(method)
        });
        processed.add(method.id);
      });

      y += sectionHeight + sectionGap;
      return;
    }

    if (node.type === "method") {
      const classId = nearestAncestorOfType(node.id, "class", containment);
      const classNode = classId ? containment.nodeById.get(classId) : null;
      const className = classNode ? classDisplayName(classNode) : "method";

      slots.push({
        node,
        x: classNode ? methodX : classX + 34,
        y,
        width: SYMBOL_NODE_WIDTH,
        height: SYMBOL_NODE_HEIGHT,
        label: methodDisplayName(node),
        pathLabel: className,
        summary: methodDisplayName(node),
        countLabel: formatLineRange(node)
      });
      processed.add(node.id);
      y += SYMBOL_NODE_HEIGHT + sectionGap;
      return;
    }

    slots.push({
      node,
      x: classX,
      y,
      width: SYMBOL_NODE_WIDTH,
      height: SYMBOL_NODE_HEIGHT,
      label: node.type === "function" ? functionDisplayName(node) : compactSymbolName(node),
      pathLabel: node.type === "function" ? "function" : node.type,
      summary:
        node.type === "function" ? functionDisplayName(node) : symbolSummary(node, nodeSummary(node)),
      countLabel: formatLineRange(node)
    });
    processed.add(node.id);
    y += SYMBOL_NODE_HEIGHT + sectionGap;
  });

  return slots;
}

function nearestAncestorOfType(
  nodeId: string,
  type: string,
  containment: ContainmentIndex
): string | null {
  const visited = new Set<string>();
  let current = containment.parentByChild.get(nodeId);

  while (current && !visited.has(current)) {
    visited.add(current);
    const node = containment.nodeById.get(current);
    if (node?.type === type) {
      return node.id;
    }
    current = containment.parentByChild.get(current);
  }

  return null;
}

function deriveContainment(graph: GraphResponse | null): ContainmentIndex {
  const nodeById = new Map<string, CodeNode>();
  const childrenByParent = new Map<string, string[]>();
  const parentByChild = new Map<string, string>();
  const fileByNode = new Map<string, string>();
  const descendantsByFile = new Map<string, string[]>();

  if (!graph) {
    return { nodeById, childrenByParent, parentByChild, fileByNode, descendantsByFile };
  }

  graph.nodes.forEach((node) => {
    nodeById.set(node.id, node);
  });

  graph.edges
    .filter((edge) => edge.type === "contains")
    .forEach((edge) => {
      const children = childrenByParent.get(edge.source) ?? [];
      children.push(edge.target);
      childrenByParent.set(edge.source, children);
      if (!parentByChild.has(edge.target)) {
        parentByChild.set(edge.target, edge.source);
      }
    });

  const fileNodes = graph.nodes.filter((node) => node.type === "file");
  fileNodes.forEach((file) => {
    fileByNode.set(file.id, file.id);
    descendantsByFile.set(file.id, []);
  });

  graph.nodes.forEach((node) => {
    const fileId = findFileAncestor(node.id, nodeById, parentByChild, fileNodes);
    if (fileId) {
      fileByNode.set(node.id, fileId);
      if (node.id !== fileId) {
        const descendants = descendantsByFile.get(fileId) ?? [];
        descendants.push(node.id);
        descendantsByFile.set(fileId, descendants);
      }
    }
  });

  descendantsByFile.forEach((ids) => {
    ids.sort((left, right) => compareBySourceOrder(nodeById.get(left), nodeById.get(right)));
  });

  return { nodeById, childrenByParent, parentByChild, fileByNode, descendantsByFile };
}

function findFileAncestor(
  nodeId: string,
  nodeById: Map<string, CodeNode>,
  parentByChild: Map<string, string>,
  fileNodes: CodeNode[]
): string | null {
  const node = nodeById.get(nodeId);
  if (!node) {
    return null;
  }
  if (node.type === "file") {
    return node.id;
  }

  const visited = new Set<string>();
  let currentId: string | undefined = nodeId;
  while (currentId && !visited.has(currentId)) {
    visited.add(currentId);
    const parentId = parentByChild.get(currentId);
    if (!parentId) {
      break;
    }
    const parent = nodeById.get(parentId);
    if (parent?.type === "file") {
      return parent.id;
    }
    currentId = parentId;
  }

  if (node.file_path) {
    return fileNodes.find((file) => file.file_path === node.file_path)?.id ?? null;
  }

  return null;
}

function filterRawGraph(
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

function collectOverviewFileIds(
  nodes: CodeNode[],
  edges: CodeEdge[],
  containment: ContainmentIndex
): Set<string> {
  const fileIds = new Set<string>();

  nodes.forEach((node) => {
    const fileId = containment.fileByNode.get(node.id);
    if (fileId) {
      fileIds.add(fileId);
    }
  });

  edges.forEach((edge) => {
    const sourceFile = containment.fileByNode.get(edge.source);
    const targetFile = containment.fileByNode.get(edge.target);
    if (sourceFile) {
      fileIds.add(sourceFile);
    }
    if (targetFile) {
      fileIds.add(targetFile);
    }
  });

  return fileIds;
}

function deriveFileGroups(files: CodeNode[]): FileGroup[] {
  if (files.length === 0) {
    return [];
  }

  let groups = groupFilesByDepth(files, 1);
  if (groups.size < 2 || largestGroupShare(groups, files.length) > 0.7) {
    groups = groupFilesByDepth(files, 2);
  }
  if (groups.size < 2 || largestGroupShare(groups, files.length) > 0.7) {
    groups = groupFilesByDepth(files, 3);
  }

  return [...groups.entries()]
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([groupPath, groupFiles], index) => {
      const cols = clamp(Math.ceil(Math.sqrt(groupFiles.length)), 1, 4);
      const rows = Math.ceil(groupFiles.length / cols);
      const width = GROUP_PADDING_X * 2 + cols * FILE_NODE_WIDTH + (cols - 1) * GROUP_CHILD_GAP;
      const height = GROUP_HEADER_HEIGHT + 28 + rows * FILE_NODE_HEIGHT + (rows - 1) * GROUP_CHILD_GAP;
      const childPositions = new Map<string, { x: number; y: number }>();

      groupFiles.sort(compareByPath).forEach((file, fileIndex) => {
        const col = fileIndex % cols;
        const row = Math.floor(fileIndex / cols);
        childPositions.set(file.id, {
          x: GROUP_PADDING_X + col * (FILE_NODE_WIDTH + GROUP_CHILD_GAP),
          y: GROUP_HEADER_HEIGHT + 24 + row * (FILE_NODE_HEIGHT + GROUP_CHILD_GAP)
        });
      });

      return {
        id: `group:${index}:${groupPath}`,
        name: groupPath === "~" ? "(root)" : groupPath,
        pathLabel: groupPath === "~" ? "repository root" : groupPath,
        files: groupFiles,
        width,
        height,
        childPositions
      };
    });
}

function groupFilesByDepth(files: CodeNode[], depth: number): Map<string, CodeNode[]> {
  const prefix = commonDirectoryPrefix(files.map((file) => file.file_path ?? file.name));
  const groups = new Map<string, CodeNode[]>();

  files.forEach((file) => {
    const path = file.file_path ?? file.name;
    const stripped = stripPrefix(path, prefix);
    const parts = stripped.split("/").filter(Boolean);
    const dirParts = parts.length > 1 ? parts.slice(0, -1) : [];
    const key = dirParts.length === 0 ? "~" : dirParts.slice(0, depth).join("/");
    const groupFiles = groups.get(key) ?? [];
    groupFiles.push(file);
    groups.set(key, groupFiles);
  });

  return groups;
}

function aggregateEdges(
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

function toFlowEdge(bucket: EdgeBucket, sourceOverride?: string, targetOverride?: string): FlowEdge {
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
    label: `${bucket.type}${countLabel}`,
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

function nodeSize(
  width: number,
  height: number
): Pick<FlowNode, "height" | "initialHeight" | "initialWidth" | "sourcePosition" | "style" | "targetPosition" | "width"> {
  return {
    height,
    initialHeight: height,
    initialWidth: width,
    sourcePosition: Position.Right,
    style: { width, height },
    targetPosition: Position.Left,
    width
  };
}

function styleEdgeForSelection(edge: FlowEdge, isActive: boolean, mode: GraphViewMode): FlowEdge {
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

function layoutBoxes(
  nodes: Array<{ id: string; width: number; height: number }>,
  edges: Array<{ source: string; target: string }>,
  direction: "LR" | "TB"
): Map<string, { x: number; y: number }> {
  const graph = new dagre.graphlib.Graph();
  graph.setDefaultEdgeLabel(() => ({}));
  graph.setGraph({
    edgesep: 18,
    marginx: 32,
    marginy: 32,
    nodesep: direction === "LR" ? GROUP_GAP_Y : GROUP_GAP_X,
    rankdir: direction,
    ranksep: direction === "LR" ? GROUP_GAP_X : GROUP_GAP_Y
  });

  nodes.forEach((node) => {
    graph.setNode(node.id, { width: node.width, height: node.height });
  });
  edges.forEach((edge) => {
    if (edge.source !== edge.target) {
      graph.setEdge(edge.source, edge.target);
    }
  });
  dagre.layout(graph);

  const positions = new Map<string, { x: number; y: number }>();
  nodes.forEach((node) => {
    const position = graph.node(node.id) as { x: number; y: number } | undefined;
    positions.set(node.id, {
      x: (position?.x ?? 0) - node.width / 2,
      y: (position?.y ?? 0) - node.height / 2
    });
  });

  return positions;
}

function applyVisualState(
  nodes: FlowNode[],
  edges: FlowEdge[],
  selectedVisualId: string | null,
  mode: GraphViewMode
): { nodes: FlowNode[]; edges: FlowEdge[] } {
  const anchoredNodes = nodes.map(withConnectionAnchors);

  if (!selectedVisualId) {
    return { nodes: anchoredNodes, edges };
  }

  const nodeById = new Map(anchoredNodes.map((node) => [node.id, node]));
  const selectedNode = nodeById.get(selectedVisualId);
  const selectedRawIds = new Set(selectedNode?.data.rawNodeIds ?? []);
  const selectedVisualIds = new Set<string>([selectedVisualId]);

  if (selectedNode?.data.kind === "container") {
    anchoredNodes.forEach((node) => {
      const isChild = node.parentId === selectedVisualId;
      const sharesRawNode = node.data.rawNodeIds.some((rawId) => selectedRawIds.has(rawId));
      if (isChild || sharesRawNode) {
        selectedVisualIds.add(node.id);
      }
    });
  }

  const neighbors = new Set<string>();
  const activeEdgeIds = new Set<string>();
  edges.forEach((edge) => {
    const isActive = selectedVisualIds.has(edge.source) || selectedVisualIds.has(edge.target);
    if (!isActive) {
      return;
    }
    activeEdgeIds.add(edge.id);
    if (!selectedVisualIds.has(edge.source)) {
      neighbors.add(edge.source);
    }
    if (!selectedVisualIds.has(edge.target)) {
      neighbors.add(edge.target);
    }
  });

  return {
    nodes: anchoredNodes.map((node) => {
      const isSelected = node.id === selectedVisualId;
      const isInsideSelectedContainer = selectedNode?.data.kind === "container" && selectedVisualIds.has(node.id);
      const isNeighbor = neighbors.has(node.id) || (isInsideSelectedContainer && !isSelected);
      const isFaded = !isSelected && !isNeighbor;
      return {
        ...node,
        data: {
          ...node.data,
          isSelected,
          isNeighbor,
          isFaded
        }
      };
    }),
    edges: edges.map((edge) => {
      const isActive = activeEdgeIds.has(edge.id);
      return styleEdgeForSelection(edge, isActive, mode);
    })
  };
}

function withConnectionAnchors(node: FlowNode): FlowNode {
  return {
    ...node,
    sourcePosition: Position.Right,
    targetPosition: Position.Left
  };
}

function pruneHiddenVisualGraph(
  graph: { nodes: FlowNode[]; edges: FlowEdge[] },
  hiddenVisualIds: Set<string>
): { nodes: FlowNode[]; edges: FlowEdge[] } {
  if (hiddenVisualIds.size === 0) {
    return graph;
  }

  const hiddenWithChildren = new Set(hiddenVisualIds);
  let changed = true;
  while (changed) {
    changed = false;
    graph.nodes.forEach((node) => {
      if (node.parentId && hiddenWithChildren.has(node.parentId) && !hiddenWithChildren.has(node.id)) {
        hiddenWithChildren.add(node.id);
        changed = true;
      }
    });
  }

  const nodes = graph.nodes.filter((node) => !hiddenWithChildren.has(node.id));
  const visibleIds = new Set(nodes.map((node) => node.id));
  const edges = graph.edges.filter((edge) => visibleIds.has(edge.source) && visibleIds.has(edge.target));

  return { nodes, edges };
}

function toCodeVisualData(
  node: CodeNode,
  options: {
    containment: ContainmentIndex;
    label?: string;
    fileId?: string;
    rawNodeIds: string[];
    summary: string;
    countLabel?: string;
    pathLabel?: string;
    lineLabel?: string;
    stats?: NodeStats;
    statsLabel?: string;
    isContained: boolean;
    isExternal: boolean;
  }
): CodeVisualData {
  const tone = nodeTone(node.type);
  const statsLabel =
    options.statsLabel ??
    (options.stats ? `${options.stats.outgoing} out / ${options.stats.incoming} in` : "No visible edges");

  return {
    kind: "code",
    label: options.label ?? node.name,
    nodeType: node.type,
    summary: options.summary,
    pathLabel: options.pathLabel ?? compactFilePath(node.file_path ?? node.name),
    lineLabel: options.lineLabel ?? formatLineRange(node),
    countLabel: options.countLabel,
    statsLabel,
    accentColor: tone.border,
    codeNode: node,
    fileId: options.fileId,
    rawNodeIds: options.rawNodeIds,
    isSelected: false,
    isNeighbor: false,
    isFaded: false,
    isContained: options.isContained,
    isExternal: options.isExternal
  };
}

type Portal = {
  visualId: string;
  direction: "in" | "out";
  bucket: EdgeBucket;
  node: CodeNode | null;
};

function collectFilePortals(
  fileId: string,
  selectedSymbolId: string | null,
  edges: CodeEdge[],
  containment: ContainmentIndex,
  graph: GraphResponse
): Portal[] {
  const fileRawIds = new Set([fileId, ...(containment.descendantsByFile.get(fileId) ?? [])]);
  const sourceIds = selectedSymbolId ? new Set([selectedSymbolId]) : fileRawIds;
  const moduleVisualId = "portal:dependency";
  const rawToVisual = new Map<string, string>();
  const portalNodes = new Map<string, CodeNode | null>();

  graph.nodes.forEach((node) => {
    if (node.type === "module") {
      rawToVisual.set(node.id, moduleVisualId);
      portalNodes.set(moduleVisualId, null);
      return;
    }

    const nodeFileId = containment.fileByNode.get(node.id);
    if (nodeFileId && nodeFileId !== fileId) {
      const visualId = `portal:${nodeFileId}`;
      rawToVisual.set(node.id, visualId);
      portalNodes.set(visualId, containment.nodeById.get(nodeFileId) ?? null);
    }
  });

  const buckets = new Map<string, Portal>();
  edges
    .filter((edge) => edge.type !== "contains")
    .forEach((edge) => {
      const sourceInside = sourceIds.has(edge.source);
      const targetInside = sourceIds.has(edge.target);
      if (sourceInside === targetInside) {
        return;
      }

      const externalRawId = sourceInside ? edge.target : edge.source;
      const baseVisualId = rawToVisual.get(externalRawId);
      if (!baseVisualId) {
        return;
      }

      const direction: "in" | "out" = sourceInside ? "out" : "in";
      const visualId = `portal:${direction}:${baseVisualId}`;
      const key = `${direction}:${visualId}:${edge.type}`;
      const existing = buckets.get(key);
      if (existing) {
        existing.bucket.count += 1;
        existing.bucket.rawEdgeIds.push(edge.id);
        existing.bucket.hasInferred = existing.bucket.hasInferred || edge.is_inferred;
      } else {
        buckets.set(key, {
          visualId,
          direction,
          node: portalNodes.get(baseVisualId) ?? null,
          bucket: {
            id: `portal-edge:${buckets.size}:${direction}:${edge.type}`,
            source: direction === "out" ? fileId : visualId,
            target: direction === "out" ? visualId : fileId,
            type: edge.type,
            count: 1,
            rawEdgeIds: [edge.id],
            hasInferred: edge.is_inferred
          }
        });
      }
    });

  return [...buckets.values()].sort((left, right) => right.bucket.count - left.bucket.count);
}

function portalToNode(
  portal: Portal,
  position: { x: number; y: number },
  containment: ContainmentIndex
): FlowNode {
  if (!portal.node) {
    return {
      id: portal.visualId,
      type: "container",
      position,
      data: {
        kind: "container",
        title: "External Dependencies",
        subtitle: "module portal",
        containerType: "dependency",
        pathLabel: "collapsed import target",
        countLabel: `${portal.bucket.count}`,
        statsLabel: `${portal.direction === "out" ? "outgoing" : "incoming"} ${portal.bucket.type}`,
        accentColor: nodeTone("module").border,
        rawNodeIds: portal.bucket.rawEdgeIds,
        isSelected: false,
        isNeighbor: false,
        isFaded: false,
        isFocusedViaChild: false,
        isCompact: true
      },
      ...nodeSize(FILE_NODE_WIDTH, 134),
      selectable: true,
      draggable: false
    };
  }

  const descendants = containment.descendantsByFile.get(portal.node.id) ?? [];
  return {
    id: portal.visualId,
    type: "code",
    position,
    data: toCodeVisualData(portal.node, {
      containment,
      fileId: portal.node.id,
      rawNodeIds: [portal.node.id, ...descendants],
      summary: `${portal.bucket.count} ${portal.bucket.type} ${portal.direction === "out" ? "from this file" : "into this file"}`,
      countLabel: `${descendants.length}`,
      statsLabel: `${portal.direction === "out" ? "outgoing" : "incoming"} edge group`,
      isContained: false,
      isExternal: true
    }),
    ...nodeSize(FILE_NODE_WIDTH, FILE_NODE_HEIGHT),
    selectable: true,
    draggable: false
  };
}

function computeStatsByRawNode(edges: CodeEdge[]): Map<string, NodeStats> {
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

function computeStatsForNodeIds(nodeIds: string[], edges: CodeEdge[]): NodeStats {
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

function symbolDepth(nodeId: string, fileId: string, containment: ContainmentIndex): number {
  let depth = 0;
  let current = containment.parentByChild.get(nodeId);
  const visited = new Set<string>();

  while (current && current !== fileId && !visited.has(current)) {
    visited.add(current);
    const parent = containment.nodeById.get(current);
    if (parent?.type === "class" || parent?.type === "function" || parent?.type === "method") {
      depth += 1;
    }
    current = containment.parentByChild.get(current);
  }

  return depth;
}

function compareByPath(left: CodeNode, right: CodeNode): number {
  return (left.file_path ?? left.name).localeCompare(right.file_path ?? right.name);
}

function compareBySourceOrder(left?: CodeNode, right?: CodeNode): number {
  if (!left && !right) {
    return 0;
  }
  if (!left) {
    return 1;
  }
  if (!right) {
    return -1;
  }
  const leftPath = left.file_path ?? "";
  const rightPath = right.file_path ?? "";
  if (leftPath !== rightPath) {
    return leftPath.localeCompare(rightPath);
  }
  const leftLine = left.start_line ?? Number.MAX_SAFE_INTEGER;
  const rightLine = right.start_line ?? Number.MAX_SAFE_INTEGER;
  if (leftLine !== rightLine) {
    return leftLine - rightLine;
  }
  return left.name.localeCompare(right.name);
}

function largestGroupShare(groups: Map<string, CodeNode[]>, total: number): number {
  if (total === 0) {
    return 0;
  }
  return Math.max(...[...groups.values()].map((nodes) => nodes.length)) / total;
}

function commonDirectoryPrefix(paths: string[]): string {
  const dirs = paths
    .filter(Boolean)
    .map((path) => path.replaceAll("\\", "/"))
    .map((path) => {
      const slash = path.lastIndexOf("/");
      return slash >= 0 ? path.slice(0, slash + 1) : "";
    });

  if (dirs.length === 0) {
    return "";
  }

  let prefix = dirs[0];
  dirs.forEach((dir) => {
    while (prefix && !dir.startsWith(prefix)) {
      prefix = prefix.slice(0, -1);
      const slash = prefix.lastIndexOf("/");
      prefix = slash >= 0 ? prefix.slice(0, slash + 1) : "";
    }
  });

  return prefix;
}

function stripPrefix(value: string, prefix: string): string {
  const normalized = value.replaceAll("\\", "/");
  return prefix && normalized.startsWith(prefix) ? normalized.slice(prefix.length) : normalized;
}

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

function getPrimaryNode(visualData: VisualNodeData | null, containment: ContainmentIndex): CodeNode | null {
  if (!visualData) {
    return null;
  }
  if (visualData.kind === "code") {
    return visualData.codeNode;
  }
  if (visualData.primaryNodeId) {
    return containment.nodeById.get(visualData.primaryNodeId) ?? null;
  }
  return visualData.rawNodeIds.map((id) => containment.nodeById.get(id)).find(Boolean) ?? null;
}

function summarizeVisualGraph(
  graph: GraphResponse | null,
  filtered: FilteredGraph,
  visualGraph: { nodes: FlowNode[]; edges: FlowEdge[] }
): string {
  if (!graph) {
    return "No graph loaded";
  }
  return `${visualGraph.nodes.length} visual / ${filtered.nodes.length}/${graph.nodes.length} raw nodes / ${visualGraph.edges.length} edges`;
}

function miniMapColor(node: FlowNode): string {
  const data = node.data;
  if (data.kind === "container") {
    return data.accentColor;
  }
  return data.accentColor;
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
  if (node.start_line != null && node.end_line != null) {
    return `${node.start_line}-${node.end_line}`;
  }
  if (node.start_line != null) {
    return `${node.start_line}`;
  }
  return "n/a";
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

function compactFilePath(path: string): string {
  const normalized = path.replaceAll("\\", "/");
  const parts = normalized.split("/").filter(Boolean);
  if (parts.length <= 3) {
    return normalized || "scope";
  }
  return `${parts[0]}/.../${parts.slice(-2).join("/")}`;
}

function nodeSummary(node: CodeNode): string {
  const signature = typeof node.metadata.signature === "string" ? node.metadata.signature : "";
  const docstring = typeof node.metadata.docstring === "string" ? node.metadata.docstring : "";
  if (signature) {
    return signature;
  }
  if (docstring) {
    return docstring;
  }
  if (node.type === "module") {
    return "External dependency";
  }
  return compactFilePath(node.file_path ?? node.name);
}

function symbolSummary(node: CodeNode, fallback: string): string {
  const signature = typeof node.metadata.signature === "string" ? node.metadata.signature : "";
  const docstring = typeof node.metadata.docstring === "string" ? node.metadata.docstring : "";
  if (signature) {
    return signature;
  }
  if (docstring) {
    return docstring;
  }
  return fallback;
}

function compactSymbolName(node: CodeNode): string {
  const rawName = node.name || node.symbol_id || "unnamed";
  if (node.type === "class") {
    return classDisplayName(node);
  }
  if (node.type === "method") {
    return methodDisplayName(node);
  }
  if (node.type === "function") {
    return functionDisplayName(node);
  }
  const withoutParens = rawName.split("(")[0] || rawName;
  const separators = ["::", "."];

  for (const separator of separators) {
    const index = withoutParens.lastIndexOf(separator);
    if (index >= 0 && index < withoutParens.length - separator.length) {
      return withoutParens.slice(index + separator.length);
    }
  }

  return withoutParens;
}

function classDisplayName(node: CodeNode): string {
  const signature = typeof node.metadata.signature === "string" ? node.metadata.signature : "";
  const fromSignature = signature.match(/\bclass\s+([A-Za-z_$][\w$]*)/)?.[1];
  return compactQualifiedName(fromSignature || node.name || node.symbol_id || "unnamed");
}

function methodDisplayName(node: CodeNode): string {
  const signature = typeof node.metadata.signature === "string" ? node.metadata.signature : "";
  const fromSignature =
    signature.match(/\bdef\s+([A-Za-z_$][\w$]*)\s*\(/)?.[1] ??
    signature.match(/\basync\s+def\s+([A-Za-z_$][\w$]*)\s*\(/)?.[1];
  return compactQualifiedName(fromSignature || node.name || node.symbol_id || "unnamed");
}

function functionDisplayName(node: CodeNode): string {
  const signature = typeof node.metadata.signature === "string" ? node.metadata.signature : "";
  const fromSignature =
    signature.match(/\basync\s+def\s+([A-Za-z_$][\w$]*)\s*\(/)?.[1] ??
    signature.match(/\bdef\s+([A-Za-z_$][\w$]*)\s*\(/)?.[1] ??
    signature.match(/\bfunction\s+([A-Za-z_$][\w$]*)\s*\(/)?.[1];
  return compactQualifiedName(fromSignature || node.name || node.symbol_id || "unnamed");
}

function compactQualifiedName(value: string): string {
  const withoutKeyword = value.replace(/^(class|def|async\s+def|function|method)\s+/, "");
  const withoutParens = withoutKeyword.split("(")[0] || withoutKeyword;
  const separators = ["::", "."];

  for (const separator of separators) {
    const index = withoutParens.lastIndexOf(separator);
    if (index >= 0 && index < withoutParens.length - separator.length) {
      return withoutParens.slice(index + separator.length);
    }
  }

  return withoutParens;
}

function modeHint(mode: GraphViewMode): string {
  switch (mode) {
    case "overview":
      return "Files are grouped by readable folders; calls and imports are aggregated.";
    case "file":
      return "This view expands one file in source order and keeps cross-file links as portals.";
    case "focus":
      return "Only the selected node and its one-hop neighborhood are shown.";
  }
}

function nodeTone(type: string): { border: string; background: string } {
  switch (type) {
    case "repository":
      return { background: "#13251d", border: "#69b779" };
    case "directory":
      return { background: "#172129", border: "#5aa9c8" };
    case "file":
      return { background: "#151f2d", border: "#6e9ee8" };
    case "module":
      return { background: "#281d2c", border: "#c78be8" };
    case "class":
      return { background: "#242014", border: "#d7b65c" };
    case "function":
      return { background: "#14251d", border: "#63c08a" };
    case "method":
      return { background: "#241b22", border: "#e0829d" };
    default:
      return { background: "#171717", border: "#a39787" };
  }
}

function edgeTone(type: string): { stroke: string; active: string; label: string } {
  switch (type) {
    case "contains":
      return { stroke: "rgba(212, 165, 116, 0.35)", active: "rgba(232, 196, 154, 0.88)", label: "#d4a574" };
    case "imports":
      return { stroke: "#6e9ee8", active: "#a9c6f5", label: "#a9c6f5" };
    case "calls":
      return { stroke: "#63c08a", active: "#a7dfba", label: "#a7dfba" };
    default:
      return { stroke: "rgba(163, 151, 135, 0.58)", active: "#e8c49a", label: "#a39787" };
  }
}
