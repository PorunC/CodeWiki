import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent } from "react";

import { analyzeRepo, updateRepo } from "../../api/runs";
import type { GraphResponse } from "../../api/types";
import { useRepos } from "../../hooks/useRepos";
import type { HiddenVisualNodeOption } from "../GraphFiltersPanel";
import {
  collectTypes,
  deriveContainment,
  filterKey,
  filterRawGraph,
  summarizeVisualGraph,
  toggleSetValue,
  type FlowNode,
  type GraphViewMode
} from "../graphModel";
import {
  onHideVisualNode,
  onHighlightRelatedNodes,
  onOpenFileDetail,
  onOpenSourceRef,
  type SourceRefNavigationDetail
} from "../navigationEvents";
import {
  canShowInFileDetail,
  findBestNodeForSourceRef,
  findOverviewVisualIdForRawNode,
  normalizeSourceRefDetail
} from "../navigation/sourceRefMatching";
import { useVisualGraph } from "../useVisualGraph";
import { useRepoGraph } from "./useRepoGraph";

export function useGraphPageController({
  selectedRepoId,
  onSelectedRepoChange
}: {
  selectedRepoId: string;
  onSelectedRepoChange: (repoId: string) => void;
}) {
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
  const [graphReloadToken, setGraphReloadToken] = useState(0);
  const [analysisTask, setAnalysisTask] = useState<"analyze" | "update" | null>(null);
  const [analysisMessage, setAnalysisMessage] = useState<string | null>(null);
  const pendingRelatedNodeIdsRef = useRef<string[]>([]);
  const pendingSourceRefRef = useRef<SourceRefNavigationDetail | null>(null);

  const { repos, selectedRepo, loading: repoLoading, error: repoError } = useRepos({
    selectedRepoId,
    onRepoChange: onSelectedRepoChange
  });

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

  const resetGraphSelection = useCallback(() => {
    setSelectedNodeId(null);
    setSelectedVisualId(null);
    setSelectedFileId(null);
    setFocusNodeId(null);
    setHiddenVisualIds(new Set());
    setHighlightedRawNodeIds(new Set());
  }, []);

  const handleGraphLoaded = useCallback(
    (repoGraph: GraphResponse) => {
      setError(null);
      const firstFile = repoGraph.nodes.find((node) => node.type === "file") ?? repoGraph.nodes[0] ?? null;

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
    },
    [applyRelatedNodeHighlight, applySourceRefNavigation]
  );

  const { graph, loading: graphLoading } = useRepoGraph({
    selectedRepoId,
    reloadToken: graphReloadToken,
    onGraphLoaded: handleGraphLoaded,
    onGraphReset: resetGraphSelection,
    onGraphError: setError
  });

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

  const selectedNodeEdges = useMemo(() => {
    const rawIds = new Set(selectedDetailRawIds);
    return graph?.edges.filter((edge) => rawIds.has(edge.source) || rawIds.has(edge.target)) ?? [];
  }, [graph?.edges, selectedDetailRawIds]);

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

  const showAllHiddenNodes = useCallback(() => {
    setHiddenVisualIds(new Set());
  }, []);

  const clearHighlights = useCallback(() => {
    setHighlightedRawNodeIds(new Set());
  }, []);

  const openFileDetail = useCallback((fileId: string) => {
    setSelectedVisualId(`file-detail:${fileId}`);
    setSelectedNodeId(fileId);
    setSelectedFileId(fileId);
    setFocusNodeId(fileId);
    setViewMode("file");
  }, []);

  const runFullAnalysis = useCallback(async () => {
    if (!selectedRepoId || analysisTask) {
      return;
    }
    setAnalysisTask("analyze");
    setAnalysisMessage("Running full analysis...");
    setError(null);
    try {
      const result = await analyzeRepo(selectedRepoId);
      setAnalysisMessage(
        `Analysis complete: ${result.node_count} nodes, ${result.edge_count} edges, ${result.community_count} communities.`
      );
      setGraphReloadToken((value) => value + 1);
    } catch (apiError) {
      setAnalysisMessage(null);
      setError(apiError instanceof Error ? apiError.message : "Repository analysis failed");
    } finally {
      setAnalysisTask(null);
    }
  }, [analysisTask, selectedRepoId]);

  const runIncrementalUpdate = useCallback(async () => {
    if (!selectedRepoId || analysisTask) {
      return;
    }
    setAnalysisTask("update");
    setAnalysisMessage("Running incremental update...");
    setError(null);
    try {
      const result = await updateRepo(selectedRepoId, {
        refresh_chunks: true,
        regenerate_wiki: true
      });
      const staleSuffix = result.stale_pages.length ? ` ${result.stale_pages.length} wiki pages refreshed.` : "";
      setAnalysisMessage(
        `Update complete: ${result.node_count} nodes, ${result.edge_count} edges, ${result.chunk_count} chunks.${staleSuffix}`
      );
      setGraphReloadToken((value) => value + 1);
    } catch (apiError) {
      setAnalysisMessage(null);
      setError(apiError instanceof Error ? apiError.message : "Repository update failed");
    } finally {
      setAnalysisTask(null);
    }
  }, [analysisTask, selectedRepoId]);

  useEffect(() => {
    return onOpenFileDetail((detail) => {
      const fileId = detail?.fileId;
      if (fileId) {
        openFileDetail(fileId);
      }
    });
  }, [openFileDetail]);

  useEffect(() => {
    return onHideVisualNode((detail) => {
      const nodeId = detail?.nodeId;
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
    });
  }, []);

  useEffect(() => {
    return onHighlightRelatedNodes((detail) => {
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
    });
  }, [applyRelatedNodeHighlight, graph, onSelectedRepoChange, selectedRepoId]);

  useEffect(() => {
    return onOpenSourceRef((eventDetail) => {
      const detail = normalizeSourceRefDetail(eventDetail);
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
    });
  }, [applySourceRefNavigation, graph, onSelectedRepoChange, selectedRepoId]);

  const handleNodeClick = useCallback(
    (_: MouseEvent, node: FlowNode) => {
      const data = node.data;
      const primaryNodeId = data.kind === "container" ? data.primaryNodeId ?? null : data.codeNode.id;
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

  return {
    repos,
    selectedRepo,
    repoLoading,
    repoError,
    error,
    analysisTask,
    analysisMessage,
    viewMode,
    selectedFileId,
    selectedNodeId,
    nodeTypes,
    edgeTypes,
    selectedNodeTypes,
    selectedEdgeTypes,
    showInferredCalls,
    highlightedRawNodeIds,
    highlightLabel,
    hiddenNodes,
    graphStats,
    graph,
    visualGraph,
    selectedVisualData,
    selectedNode,
    selectedNodeEdges,
    containment,
    flowKey,
    isLoading,
    graphLoaded: Boolean(graph),
    actions: {
      selectMode,
      toggleNodeType,
      toggleEdgeType,
      setShowInferredCalls,
      resetFilters,
      showHiddenNode,
      showAllHiddenNodes,
      clearHighlights,
      openFileDetail,
      runFullAnalysis,
      runIncrementalUpdate,
      handleNodeClick,
      handleNodeDoubleClick,
      handleNavigateToNode
    }
  };
}
