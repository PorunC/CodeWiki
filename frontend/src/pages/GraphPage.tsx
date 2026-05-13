import { GraphFiltersPanel } from "../graph/GraphFiltersPanel";
import { GraphFlowCanvas } from "../graph/GraphFlowCanvas";
import { GraphToolbar } from "../graph/GraphToolbar";
import { NodeDetails } from "../graph/NodeDetails";
import { useGraphPageController } from "../graph/hooks/useGraphPageController";

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

  const {
    repos,
    selectedRepo,
    repoLoading,
    repoError,
    error,
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
    graphLoaded,
    actions
  } = controller;

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
        onModeSelect={actions.selectMode}
      />

      {repoError || error ? <div className="state-banner error-banner">{repoError ?? error}</div> : null}
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

      <div className="graph-workspace">
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
