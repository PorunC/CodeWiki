import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent } from "react";

import {
  getRepoGraph,
  getRepos,
  type GraphResponse,
  type RepoSummary
} from "../api/client";
import { GraphFiltersPanel, type HiddenVisualNodeOption } from "../graph/GraphFiltersPanel";
import { GraphFlowCanvas } from "../graph/GraphFlowCanvas";
import { GraphHeader } from "../graph/GraphHeader";
import { GraphToolbar } from "../graph/GraphToolbar";
import { NodeDetails } from "../graph/NodeDetails";
import { useVisualGraph } from "../graph/useVisualGraph";
import {
  collectTypes,
  deriveContainment,
  filterKey,
  filterRawGraph,
  summarizeVisualGraph,
  toggleSetValue,
  type FlowNode,
  type GraphViewMode
} from "../graph/graphModel";

export function GraphPage({
  selectedRepoId,
  onSelectedRepoChange
}: {
  selectedRepoId: string;
  onSelectedRepoChange: (repoId: string) => void;
}) {
  const [repos, setRepos] = useState<RepoSummary[]>([]);
  const [graph, setGraph] = useState<GraphResponse | null>(null);
  const [repoLoading, setRepoLoading] = useState(true);
  const [graphLoading, setGraphLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<GraphViewMode>("overview");
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedVisualId, setSelectedVisualId] = useState<string | null>(null);
  const [selectedFileId, setSelectedFileId] = useState<string | null>(null);
  const [focusNodeId, setFocusNodeId] = useState<string | null>(null);
  const [selectedNodeTypes, setSelectedNodeTypes] = useState<Set<string>>(new Set());
  const [selectedEdgeTypes, setSelectedEdgeTypes] = useState<Set<string>>(new Set());
  const [showInferredCalls, setShowInferredCalls] = useState(true);
  const [hiddenVisualIds, setHiddenVisualIds] = useState<Set<string>>(new Set());
  const [highlightedRawNodeIds, setHighlightedRawNodeIds] = useState<Set<string>>(new Set());
  const pendingRelatedNodeIdsRef = useRef<string[]>([]);
  const [refreshNonce, setRefreshNonce] = useState(0);

  const applyRelatedNodeHighlight = useCallback((repoGraph: GraphResponse, nodeIds: string[]) => {
    const graphNodeIds = new Set(repoGraph.nodes.map((node) => node.id));
    const validNodeIds = nodeIds.filter((nodeId) => graphNodeIds.has(nodeId));
    setHighlightedRawNodeIds(new Set(validNodeIds));
    if (validNodeIds.length === 0) {
      return;
    }

    const firstNodeId = validNodeIds[0];
    const firstNode = repoGraph.nodes.find((node) => node.id === firstNodeId) ?? null;
    const visualId = findOverviewVisualIdForRawNode(repoGraph, firstNodeId);
    const visualNode = repoGraph.nodes.find((node) => node.id === visualId) ?? null;
    setSelectedNodeId(firstNodeId);
    setSelectedVisualId(visualId);
    setSelectedFileId(firstNode?.type === "file" ? firstNode.id : visualNode?.type === "file" ? visualNode.id : null);
    setFocusNodeId(firstNodeId);
    setViewMode("overview");
  }, []);

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
        if (!selectedRepoId && repoList[0]) {
          onSelectedRepoChange(repoList[0].id);
        }
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
  }, [onSelectedRepoChange, selectedRepoId]);

  useEffect(() => {
    if (!selectedRepoId) {
      setGraph(null);
      setSelectedNodeId(null);
      setSelectedVisualId(null);
      setSelectedFileId(null);
      setFocusNodeId(null);
      setHiddenVisualIds(new Set());
      setHighlightedRawNodeIds(new Set());
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
        setFocusNodeId(firstFile?.id ?? null);
        setHiddenVisualIds(new Set());
        setViewMode("overview");
        if (pendingRelatedNodeIdsRef.current.length > 0) {
          applyRelatedNodeHighlight(repoGraph, pendingRelatedNodeIdsRef.current);
          pendingRelatedNodeIdsRef.current = [];
        } else {
          setHighlightedRawNodeIds(new Set());
        }
      })
      .catch((apiError: unknown) => {
        if (!cancelled) {
          setGraph(null);
          setSelectedNodeId(null);
          setSelectedVisualId(null);
          setSelectedFileId(null);
          setFocusNodeId(null);
          setHiddenVisualIds(new Set());
          setHighlightedRawNodeIds(new Set());
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
  }, [applyRelatedNodeHighlight, refreshNonce, selectedRepoId]);

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

  const { baseVisualGraph, visualGraph, selectedVisualData } = useVisualGraph({
    graph,
    filteredGraph,
    containment,
    viewMode,
    selectedFileId,
    selectedNodeId: viewMode === "focus" ? focusNodeId : selectedNodeId,
    selectedVisualId,
    hiddenVisualIds,
    highlightedRawNodeIds
  });

  const hiddenNodes = useMemo<HiddenVisualNodeOption[]>(() => {
    const nodeById = new Map(baseVisualGraph.nodes.map((node) => [node.id, node]));
    return [...hiddenVisualIds]
      .map((nodeId) => {
        const node = nodeById.get(nodeId);
        if (!node) {
          return {
            id: nodeId,
            label: nodeId,
            type: "hidden",
            meta: "not in current view"
          };
        }
        const data = node.data;
        return {
          id: node.id,
          label: data.kind === "container" ? data.title : data.label,
          type: data.kind === "container" ? data.containerType : data.nodeType,
          meta: data.pathLabel
        };
      })
      .sort((left, right) => left.label.localeCompare(right.label));
  }, [baseVisualGraph.nodes, hiddenVisualIds]);

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

  const showHiddenNode = useCallback((nodeId: string) => {
    setHiddenVisualIds((current) => {
      const next = new Set(current);
      next.delete(nodeId);
      return next;
    });
  }, []);

  const openFileDetail = useCallback((fileId: string) => {
    setSelectedVisualId(`file-detail:${fileId}`);
    setSelectedNodeId(fileId);
    setSelectedFileId(fileId);
    setFocusNodeId(fileId);
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

  useEffect(() => {
    const handleHighlightRelatedNodes = (event: Event) => {
      const detail = (event as CustomEvent<{ repoId?: string; nodeIds?: string[] }>).detail;
      const repoId = detail?.repoId;
      const nodeIds = detail?.nodeIds?.filter(Boolean) ?? [];
      if (repoId && repoId !== selectedRepoId) {
        pendingRelatedNodeIdsRef.current = nodeIds;
        onSelectedRepoChange(repoId);
        return;
      }
      if (!graph) {
        pendingRelatedNodeIdsRef.current = nodeIds;
        return;
      }
      applyRelatedNodeHighlight(graph, nodeIds);
    };

    window.addEventListener("codewiki:highlight-related-nodes", handleHighlightRelatedNodes);
    return () => window.removeEventListener("codewiki:highlight-related-nodes", handleHighlightRelatedNodes);
  }, [applyRelatedNodeHighlight, graph, onSelectedRepoChange, selectedRepoId]);

  const handleNodeClick = useCallback(
    (_: MouseEvent, node: FlowNode) => {
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
    (_: MouseEvent, node: FlowNode) => {
      const data = node.data;
      if (data.kind === "code" && data.nodeType === "file" && data.fileId) {
        openFileDetail(data.fileId);
        return;
      }

      const primaryNodeId = data.kind === "container" ? data.primaryNodeId ?? null : data.codeNode.id;
      if (viewMode === "focus" && primaryNodeId) {
        setFocusNodeId(primaryNodeId);
        setSelectedNodeId(primaryNodeId);
        setSelectedVisualId(primaryNodeId);
      }
    },
    [openFileDetail, viewMode]
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
        setFocusNodeId(selectedNodeId);
        setSelectedVisualId(selectedNodeId);
      }
    },
    [selectedFileId, selectedNodeId]
  );

  const isLoading = repoLoading || graphLoading;
  const layoutKey =
    viewMode === "file" ? selectedFileId ?? "none" : viewMode === "focus" ? focusNodeId ?? "none" : "stable";
  const flowKey = `${selectedRepoId}:${viewMode}:${layoutKey}:${filterKey(selectedNodeTypes)}:${filterKey(
    selectedEdgeTypes
  )}:${showInferredCalls}`;

  return (
    <section id="graph" className="graph-panel">
      <GraphHeader
        selectedRepoId={selectedRepoId}
        graphLoading={graphLoading}
        onRefresh={() => setRefreshNonce((nonce) => nonce + 1)}
      />

      <GraphToolbar
        repos={repos}
        selectedRepo={selectedRepo}
        selectedRepoId={selectedRepoId}
        repoLoading={repoLoading}
        viewMode={viewMode}
        selectedFileId={selectedFileId}
        selectedNodeId={selectedNodeId}
        graphStats={graphStats}
        onRepoChange={onSelectedRepoChange}
        onModeSelect={selectMode}
      />

      {error ? <div className="state-banner error-banner">{error}</div> : null}
      {highlightedRawNodeIds.size > 0 ? (
        <div className="state-banner ask-highlight-banner">
          <span>{highlightedRawNodeIds.size} Ask-related nodes highlighted.</span>
          <button type="button" onClick={() => setHighlightedRawNodeIds(new Set())}>
            Clear
          </button>
        </div>
      ) : null}
      {!isLoading && repos.length === 0 ? (
        <div className="state-banner">No repositories registered yet.</div>
      ) : null}

      <div className="graph-workspace">
        <GraphFiltersPanel
          viewMode={viewMode}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          selectedNodeTypes={selectedNodeTypes}
          selectedEdgeTypes={selectedEdgeTypes}
          showInferredCalls={showInferredCalls}
          graphLoaded={Boolean(graph)}
          hiddenNodes={hiddenNodes}
          onNodeTypeToggle={toggleNodeType}
          onEdgeTypeToggle={toggleEdgeType}
          onShowInferredCallsChange={setShowInferredCalls}
          onResetFilters={resetFilters}
          onShowHiddenNode={showHiddenNode}
          onShowAllHiddenNodes={() => setHiddenVisualIds(new Set())}
        />

        <GraphFlowCanvas
          isLoading={isLoading}
          graphLoaded={Boolean(graph)}
          nodes={visualGraph.nodes}
          edges={visualGraph.edges}
          flowKey={flowKey}
          onNodeClick={handleNodeClick}
          onNodeDoubleClick={handleNodeDoubleClick}
        />

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

function findOverviewVisualIdForRawNode(graph: GraphResponse, rawNodeId: string): string | null {
  const nodeById = new Map(graph.nodes.map((node) => [node.id, node]));
  const node = nodeById.get(rawNodeId);
  if (!node) {
    return null;
  }
  if (node.type === "module") {
    return "dependency:external";
  }
  if (node.type === "file" || node.type === "directory" || node.type === "repository") {
    return node.id;
  }

  const parentByChild = new Map(
    graph.edges
      .filter((edge) => edge.type === "contains")
      .map((edge) => [edge.target, edge.source])
  );
  let currentId: string | undefined = rawNodeId;
  while (currentId) {
    const currentNode = nodeById.get(currentId);
    if (currentNode?.type === "file") {
      return currentNode.id;
    }
    currentId = parentByChild.get(currentId);
  }
  return rawNodeId;
}
