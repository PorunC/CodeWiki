import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent } from "react";

import {
  type CodeNode,
  getRepoGraph,
  getRepos,
  type GraphResponse,
  type RepoSummary
} from "../api/client";
import { GraphFiltersPanel, type HiddenVisualNodeOption } from "../graph/GraphFiltersPanel";
import { GraphFlowCanvas } from "../graph/GraphFlowCanvas";
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
  onSelectedRepoChange,
  isActiveSection
}: {
  selectedRepoId: string;
  onSelectedRepoChange: (repoId: string) => void;
  isActiveSection: boolean;
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
  const [highlightLabel, setHighlightLabel] = useState("Ask-related");
  const pendingRelatedNodeIdsRef = useRef<string[]>([]);
  const pendingSourceRefRef = useRef<SourceRefNavigationDetail | null>(null);

  const applyRelatedNodeHighlight = useCallback((repoGraph: GraphResponse, nodeIds: string[]) => {
    const graphNodeIds = new Set(repoGraph.nodes.map((node) => node.id));
    const validNodeIds = nodeIds.filter((nodeId) => graphNodeIds.has(nodeId));
    setHighlightLabel("Ask-related");
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

  const applySourceRefNavigation = useCallback((repoGraph: GraphResponse, detail: SourceRefNavigationDetail) => {
    const match = findBestNodeForSourceRef(repoGraph, detail);
    if (!match) {
      setHighlightLabel("Wiki source");
      setHighlightedRawNodeIds(new Set());
      setError(`No graph node matched ${detail.filePath}`);
      return;
    }

    const { fileNode, targetNode } = match;
    setError(null);
    setHighlightLabel("Wiki source");
    setHighlightedRawNodeIds(new Set([targetNode.id]));
    setSelectedNodeTypes((current) => new Set([...current, "file", targetNode.type]));
    setHiddenVisualIds((current) => {
      const next = new Set(current);
      next.delete(fileNode.id);
      next.delete(`file-detail:${fileNode.id}`);
      next.delete(targetNode.id);
      return next;
    });
    setSelectedFileId(fileNode.id);
    setSelectedNodeId(targetNode.id);
    setSelectedVisualId(targetNode.type === "file" ? `file-detail:${fileNode.id}` : targetNode.id);
    setFocusNodeId(targetNode.id);
    setViewMode("file");
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
        } else if (pendingSourceRefRef.current) {
          applySourceRefNavigation(repoGraph, pendingSourceRefRef.current);
          pendingSourceRefRef.current = null;
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
  }, [applyRelatedNodeHighlight, applySourceRefNavigation, selectedRepoId]);

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

  const handleNavigateToNode = useCallback(
    (nodeId: string, edgeType?: string) => {
      if (!graph) {
        return;
      }
      const targetNode = graph.nodes.find((candidate) => candidate.id === nodeId);
      if (!targetNode) {
        setError(`Node not found: ${nodeId}`);
        return;
      }

      const targetFileId = targetNode.type === "file" ? targetNode.id : containment.fileByNode.get(targetNode.id) ?? null;
      const showInFileDetail = Boolean(targetFileId && canShowInFileDetail(targetNode));
      const nextVisualId = showInFileDetail
        ? targetNode.type === "file"
          ? `file-detail:${targetFileId}`
          : targetNode.id
        : targetNode.id;

      setError(null);
      setHighlightLabel("Reference");
      setHighlightedRawNodeIds(new Set([targetNode.id]));
      setSelectedNodeTypes((current) => {
        const next = new Set(current);
        next.add(targetNode.type);
        if (targetFileId) {
          next.add("file");
        }
        return next;
      });
      if (edgeType) {
        setSelectedEdgeTypes((current) => new Set([...current, edgeType]));
      }
      setHiddenVisualIds((current) => {
        const next = new Set(current);
        const revealRawIds = new Set([targetNode.id]);
        if (targetFileId) {
          revealRawIds.add(targetFileId);
        }

        baseVisualGraph.nodes.forEach((visualNode) => {
          const shouldReveal =
            visualNode.id === targetNode.id ||
            visualNode.id === targetFileId ||
            visualNode.id === `file-detail:${targetFileId}` ||
            visualNode.id === nextVisualId ||
            visualNode.data.rawNodeIds.some((rawId) => revealRawIds.has(rawId));
          if (shouldReveal) {
            next.delete(visualNode.id);
          }
        });
        next.delete(targetNode.id);
        if (targetFileId) {
          next.delete(targetFileId);
          next.delete(`file-detail:${targetFileId}`);
        }
        next.delete(nextVisualId);
        return next;
      });
      setSelectedFileId(targetFileId);
      setSelectedNodeId(targetNode.id);
      setFocusNodeId(targetNode.id);
      setSelectedVisualId(nextVisualId);
      setViewMode(showInFileDetail ? "file" : "focus");
    },
    [baseVisualGraph.nodes, containment.fileByNode, graph]
  );

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

  useEffect(() => {
    const handleOpenSourceRef = (event: Event) => {
      const detail = normalizeSourceRefDetail(
        (event as CustomEvent<Partial<SourceRefNavigationDetail>>).detail
      );
      if (!detail) {
        return;
      }
      if (detail.repoId && detail.repoId !== selectedRepoId) {
        pendingSourceRefRef.current = detail;
        onSelectedRepoChange(detail.repoId);
        return;
      }
      if (!graph) {
        pendingSourceRefRef.current = detail;
        return;
      }
      applySourceRefNavigation(graph, detail);
    };

    window.addEventListener("codewiki:open-source-ref", handleOpenSourceRef);
    return () => window.removeEventListener("codewiki:open-source-ref", handleOpenSourceRef);
  }, [applySourceRefNavigation, graph, onSelectedRepoChange, selectedRepoId]);

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
    <section id="graph" className={`graph-panel${isActiveSection ? " is-nav-target" : ""}`}>
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
          <span>
            {highlightedRawNodeIds.size} {highlightLabel} node
            {highlightedRawNodeIds.size === 1 ? "" : "s"} highlighted.
          </span>
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
          onNavigateToNode={handleNavigateToNode}
        />
      </div>
    </section>
  );
}

type SourceRefNavigationDetail = {
  repoId?: string;
  filePath: string;
  startLine: number;
  endLine: number;
};

function normalizeSourceRefDetail(
  detail: Partial<SourceRefNavigationDetail> | undefined
): SourceRefNavigationDetail | null {
  if (!detail?.filePath) {
    return null;
  }
  const startLine = Number.isFinite(detail.startLine) ? Number(detail.startLine) : 1;
  const endLine = Number.isFinite(detail.endLine) ? Number(detail.endLine) : startLine;
  return {
    repoId: detail.repoId,
    filePath: detail.filePath,
    startLine: Math.max(1, Math.min(startLine, endLine)),
    endLine: Math.max(1, Math.max(startLine, endLine))
  };
}

function findBestNodeForSourceRef(
  graph: GraphResponse,
  detail: SourceRefNavigationDetail
): { fileNode: CodeNode; targetNode: CodeNode } | null {
  const fileNode = graph.nodes
    .filter((node) => node.type === "file")
    .find((node) => pathsMatch(node.file_path ?? node.name, detail.filePath));
  if (!fileNode) {
    return null;
  }

  const sourceSpan = detail.endLine - detail.startLine + 1;
  const symbols = graph.nodes
    .filter((node) => node.id !== fileNode.id)
    .filter((node) => pathsMatch(node.file_path, detail.filePath))
    .filter((node) => node.start_line != null)
    .map((node) => ({
      node,
      start: node.start_line ?? 1,
      end: node.end_line ?? node.start_line ?? 1
    }));

  const containing = symbols
    .filter(({ start, end }) => start <= detail.startLine && end >= detail.endLine)
    .sort(compareSourceCandidates);
  if (containing[0]) {
    return { fileNode, targetNode: containing[0].node };
  }

  if (sourceSpan <= 80) {
    const overlapping = symbols
      .map((candidate) => ({
        ...candidate,
        overlap: overlapScore(candidate, detail),
        sourceCoverage: overlapScore(candidate, detail) / sourceSpan,
        nodeCoverage: overlapScore(candidate, detail) / Math.max(1, candidate.end - candidate.start + 1)
      }))
      .filter((candidate) => candidate.overlap >= 3)
      .filter((candidate) => candidate.sourceCoverage >= 0.5 || candidate.nodeCoverage >= 0.75)
      .sort(compareOverlapCandidates);
    if (overlapping[0]) {
      return { fileNode, targetNode: overlapping[0].node };
    }
  }

  return { fileNode, targetNode: fileNode };
}

function compareSourceCandidates(
  left: { start: number; end: number },
  right: { start: number; end: number }
): number {
  const leftSpan = left.end - left.start;
  const rightSpan = right.end - right.start;
  return leftSpan - rightSpan || left.start - right.start;
}

function overlapScore(
  candidate: { start: number; end: number },
  detail: SourceRefNavigationDetail
): number {
  const overlapStart = Math.max(candidate.start, detail.startLine);
  const overlapEnd = Math.min(candidate.end, detail.endLine);
  return Math.max(0, overlapEnd - overlapStart + 1);
}

function compareOverlapCandidates(
  left: { start: number; end: number; overlap: number; sourceCoverage: number; nodeCoverage: number },
  right: { start: number; end: number; overlap: number; sourceCoverage: number; nodeCoverage: number }
): number {
  return (
    right.sourceCoverage - left.sourceCoverage ||
    right.nodeCoverage - left.nodeCoverage ||
    right.overlap - left.overlap ||
    compareSourceCandidates(left, right)
  );
}

function pathsMatch(nodePath: string | null | undefined, sourcePath: string): boolean {
  if (!nodePath) {
    return false;
  }
  const left = normalizePath(nodePath);
  const right = normalizePath(sourcePath);
  return left === right || left.endsWith(`/${right}`) || right.endsWith(`/${left}`);
}

function normalizePath(path: string): string {
  return path.replaceAll("\\", "/").replace(/^\/+/, "").replace(/\/+/g, "/");
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

function canShowInFileDetail(node: CodeNode): boolean {
  return node.type === "file" || node.type === "class" || node.type === "function" || node.type === "method";
}
