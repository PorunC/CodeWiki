import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type PointerEvent
} from "react";

import { GraphFiltersPanel } from "../graph/GraphFiltersPanel";
import { GraphFilesPanel } from "../graph/GraphFilesPanel";
import { GraphFlowCanvas } from "../graph/GraphFlowCanvas";
import { GraphToolbar } from "../graph/GraphToolbar";
import { NodeDetails } from "../graph/NodeDetails";
import { useGraphPageController } from "../graph/hooks/useGraphPageController";

const GRAPH_SIDEBAR_WIDTH_KEY = "codewiki:graph-sidebar-width";
const GRAPH_SIDEBAR_DEFAULT_WIDTH = 280;
const GRAPH_SIDEBAR_MIN_WIDTH = 220;
const GRAPH_SIDEBAR_MAX_WIDTH = 520;
const GRAPH_CANVAS_MIN_WIDTH = 420;
const GRAPH_DETAILS_WIDTH = 310;
const GRAPH_SIDEBAR_RESPONSIVE_BREAKPOINT = 900;

function initialSidebarWidth(): number {
  if (typeof window === "undefined") {
    return GRAPH_SIDEBAR_DEFAULT_WIDTH;
  }
  const storedWidth = Number(window.localStorage.getItem(GRAPH_SIDEBAR_WIDTH_KEY));
  return Number.isFinite(storedWidth)
    ? clamp(storedWidth, GRAPH_SIDEBAR_MIN_WIDTH, GRAPH_SIDEBAR_MAX_WIDTH)
    : GRAPH_SIDEBAR_DEFAULT_WIDTH;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

export function GraphPage({
  selectedRepoId,
  onSelectedRepoChange,
  isActiveSection
}: {
  selectedRepoId: string;
  onSelectedRepoChange: (repoId: string) => void;
  isActiveSection: boolean;
}) {
  const controller = useGraphPageController({
    selectedRepoId,
    onSelectedRepoChange
  });
  const workspaceRef = useRef<HTMLDivElement | null>(null);
  const dragStateRef = useRef<{ startX: number; startWidth: number } | null>(null);
  const [sidebarWidth, setSidebarWidth] = useState(initialSidebarWidth);
  const [isResizingSidebar, setIsResizingSidebar] = useState(false);

  const {
    repos,
    selectedRepo,
    repoLoading,
    repoError,
    error,
    analysisTask,
    analysisMessage,
    viewMode,
    densityMode,
    drilldownAvailable,
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
    graphLoaded,
    actions
  } = controller;

  const clampSidebarWidth = useCallback((width: number) => {
    const workspaceWidth = workspaceRef.current?.getBoundingClientRect().width ?? 0;
    const workspaceMax =
      workspaceWidth > 0
        ? Math.max(GRAPH_SIDEBAR_MIN_WIDTH, workspaceWidth - GRAPH_DETAILS_WIDTH - GRAPH_CANVAS_MIN_WIDTH)
        : GRAPH_SIDEBAR_MAX_WIDTH;
    return clamp(width, GRAPH_SIDEBAR_MIN_WIDTH, Math.min(GRAPH_SIDEBAR_MAX_WIDTH, workspaceMax));
  }, []);

  const handleSidebarResizeStart = useCallback(
    (event: PointerEvent<HTMLDivElement>) => {
      if (window.innerWidth <= GRAPH_SIDEBAR_RESPONSIVE_BREAKPOINT) {
        return;
      }
      event.preventDefault();
      dragStateRef.current = {
        startX: event.clientX,
        startWidth: sidebarWidth
      };
      setIsResizingSidebar(true);
    },
    [sidebarWidth]
  );

  const handleSidebarResizeKeyDown = useCallback(
    (event: KeyboardEvent<HTMLDivElement>) => {
      const step = event.shiftKey ? 40 : 16;
      if (event.key === "ArrowLeft") {
        event.preventDefault();
        setSidebarWidth((current) => clampSidebarWidth(current - step));
      } else if (event.key === "ArrowRight") {
        event.preventDefault();
        setSidebarWidth((current) => clampSidebarWidth(current + step));
      } else if (event.key === "Home") {
        event.preventDefault();
        setSidebarWidth((current) => clampSidebarWidth(Math.min(current, GRAPH_SIDEBAR_MIN_WIDTH)));
      } else if (event.key === "End") {
        event.preventDefault();
        setSidebarWidth((current) => clampSidebarWidth(Math.max(current, GRAPH_SIDEBAR_MAX_WIDTH)));
      }
    },
    [clampSidebarWidth]
  );

  useEffect(() => {
    if (!isResizingSidebar) {
      return;
    }

    const handlePointerMove = (event: globalThis.PointerEvent) => {
      const dragState = dragStateRef.current;
      if (!dragState) {
        return;
      }
      setSidebarWidth(clampSidebarWidth(dragState.startWidth + event.clientX - dragState.startX));
    };
    const handlePointerEnd = () => {
      dragStateRef.current = null;
      setIsResizingSidebar(false);
    };

    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", handlePointerEnd);
    window.addEventListener("pointercancel", handlePointerEnd);
    return () => {
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", handlePointerEnd);
      window.removeEventListener("pointercancel", handlePointerEnd);
    };
  }, [clampSidebarWidth, isResizingSidebar]);

  useEffect(() => {
    const handleResize = () => {
      if (window.innerWidth <= GRAPH_SIDEBAR_RESPONSIVE_BREAKPOINT) {
        return;
      }
      setSidebarWidth((current) => clampSidebarWidth(current));
    };

    handleResize();
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, [clampSidebarWidth]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    window.localStorage.setItem(GRAPH_SIDEBAR_WIDTH_KEY, String(Math.round(sidebarWidth)));
  }, [sidebarWidth]);

  return (
    <section id="graph" className={`graph-panel${isActiveSection ? " is-nav-target" : ""}`}>
      <GraphToolbar
        repos={repos}
        selectedRepo={selectedRepo}
        selectedRepoId={selectedRepoId}
        repoLoading={repoLoading}
        viewMode={viewMode}
        densityMode={densityMode}
        drilldownAvailable={drilldownAvailable}
        selectedFileId={selectedFileId}
        selectedNodeId={selectedNodeId}
        graphStats={graphStats}
        analysisTask={analysisTask}
        onRepoChange={onSelectedRepoChange}
        onModeSelect={actions.selectMode}
        onDensityModeToggle={actions.toggleDensityMode}
        onFullAnalyze={actions.runFullAnalysis}
        onIncrementalUpdate={actions.runIncrementalUpdate}
      />

      {repoError || error ? <div className="state-banner error-banner">{repoError ?? error}</div> : null}
      {analysisMessage ? <div className="state-banner analysis-banner">{analysisMessage}</div> : null}
      {highlightedRawNodeIds.size > 0 ? (
        <div className="state-banner ask-highlight-banner">
          <span>
            {highlightedRawNodeIds.size} {highlightLabel} node
            {highlightedRawNodeIds.size === 1 ? "" : "s"} highlighted.
          </span>
          <button type="button" onClick={actions.clearHighlights}>
            Clear
          </button>
        </div>
      ) : null}
      {!isLoading && repos.length === 0 ? (
        <div className="state-banner">No repositories registered yet.</div>
      ) : null}

      <div
        ref={workspaceRef}
        className={`graph-workspace${isResizingSidebar ? " is-resizing-sidebar" : ""}`}
        style={{ "--graph-sidebar-width": `${sidebarWidth}px` } as CSSProperties}
      >
        <GraphFiltersPanel
          viewMode={viewMode}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          selectedNodeTypes={selectedNodeTypes}
          selectedEdgeTypes={selectedEdgeTypes}
          showInferredCalls={showInferredCalls}
          graphLoaded={graphLoaded}
          hiddenNodes={hiddenNodes}
          onNodeTypeToggle={actions.toggleNodeType}
          onEdgeTypeToggle={actions.toggleEdgeType}
          onShowInferredCallsChange={actions.setShowInferredCalls}
          onResetFilters={actions.resetFilters}
          onShowHiddenNode={actions.showHiddenNode}
          onShowAllHiddenNodes={actions.showAllHiddenNodes}
        >
          <GraphFilesPanel
            selectedRepoId={selectedRepoId}
            graph={graph}
            selectedFileId={selectedFileId}
            onOpenFile={actions.openFileDetail}
          />
        </GraphFiltersPanel>

        <div
          className="graph-sidebar-resizer"
          role="separator"
          aria-label="Resize graph sidebar"
          aria-orientation="vertical"
          aria-valuemax={GRAPH_SIDEBAR_MAX_WIDTH}
          aria-valuemin={GRAPH_SIDEBAR_MIN_WIDTH}
          aria-valuenow={Math.round(sidebarWidth)}
          tabIndex={0}
          title="Resize graph sidebar"
          onKeyDown={handleSidebarResizeKeyDown}
          onPointerDown={handleSidebarResizeStart}
        />

        <GraphFlowCanvas
          isLoading={isLoading}
          graphLoaded={graphLoaded}
          nodes={visualGraph.nodes}
          edges={visualGraph.edges}
          flowKey={flowKey}
          onNodeClick={actions.handleNodeClick}
          onNodeDoubleClick={actions.handleNodeDoubleClick}
        />

        <NodeDetails
          visualData={selectedVisualData}
          node={selectedNode}
          edges={selectedNodeEdges}
          graph={graph}
          containment={containment}
          onNavigateToNode={actions.handleNavigateToNode}
        />
      </div>
    </section>
  );
}
