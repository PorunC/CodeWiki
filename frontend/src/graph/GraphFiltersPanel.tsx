import { Eye, FolderTree } from "lucide-react";
import type { ReactNode } from "react";

import { FilterGroup } from "./GraphControls";
import { modeHint, type CommunityLevelMode, type GraphViewMode } from "./graphModel";

export type HiddenVisualNodeOption = {
  id: string;
  label: string;
  type: string;
  meta: string;
};

export function GraphFiltersPanel({
  viewMode,
  nodeTypes,
  edgeTypes,
  selectedNodeTypes,
  selectedEdgeTypes,
  showInferredCalls,
  showIsolatedCommunities,
  communityLevelMode,
  communityHierarchyAvailable,
  detailedCommunitiesAvailable,
  hiddenIsolatedCommunityCount,
  graphLoaded,
  hiddenNodes,
  onNodeTypeToggle,
  onEdgeTypeToggle,
  onShowInferredCallsChange,
  onShowIsolatedCommunitiesChange,
  onCommunityLevelModeChange,
  onResetFilters,
  onShowHiddenNode,
  onShowAllHiddenNodes,
  children
}: {
  viewMode: GraphViewMode;
  nodeTypes: string[];
  edgeTypes: string[];
  selectedNodeTypes: Set<string>;
  selectedEdgeTypes: Set<string>;
  showInferredCalls: boolean;
  showIsolatedCommunities: boolean;
  communityLevelMode: CommunityLevelMode;
  communityHierarchyAvailable: boolean;
  detailedCommunitiesAvailable: boolean;
  hiddenIsolatedCommunityCount: number;
  graphLoaded: boolean;
  hiddenNodes: HiddenVisualNodeOption[];
  onNodeTypeToggle: (type: string) => void;
  onEdgeTypeToggle: (type: string) => void;
  onShowInferredCallsChange: (show: boolean) => void;
  onShowIsolatedCommunitiesChange: (show: boolean) => void;
  onCommunityLevelModeChange: (mode: CommunityLevelMode) => void;
  onResetFilters: () => void;
  onShowHiddenNode: (nodeId: string) => void;
  onShowAllHiddenNodes: () => void;
  children?: ReactNode;
}) {
  return (
    <aside className="graph-filters graph-sidebar">
      {children}
      <section className="graph-filter-controls" aria-label="Graph filters">
        <div className="graph-insight">
          <FolderTree size={16} />
          <span>{modeHint(viewMode)}</span>
        </div>
        <FilterGroup
          title="Node types"
          values={nodeTypes}
          selectedValues={selectedNodeTypes}
          onToggle={onNodeTypeToggle}
        />
        <FilterGroup
          title="Edge types"
          values={edgeTypes}
          selectedValues={selectedEdgeTypes}
          onToggle={onEdgeTypeToggle}
        />
        <label className="check-row">
          <input
            type="checkbox"
            checked={showInferredCalls}
            onChange={(event) => onShowInferredCallsChange(event.target.checked)}
          />
          <span>Inferred calls</span>
        </label>
        {viewMode === "overview" ? (
          <>
            {communityHierarchyAvailable ? (
              <section className="filter-subsection" aria-label="Community level">
                <div className="filter-title">Community level</div>
                <label className="check-row">
                  <input
                    type="radio"
                    name="community-level"
                    checked={communityLevelMode === "parents"}
                    disabled={!graphLoaded}
                    onChange={() => onCommunityLevelModeChange("parents")}
                  />
                  <span>Architecture areas</span>
                </label>
                <label className="check-row">
                  <input
                    type="radio"
                    name="community-level"
                    checked={communityLevelMode === "children"}
                    disabled={!graphLoaded}
                    onChange={() => onCommunityLevelModeChange("children")}
                  />
                  <span>Implementation areas</span>
                </label>
                {detailedCommunitiesAvailable ? (
                  <label className="check-row">
                    <input
                      type="radio"
                      name="community-level"
                      checked={communityLevelMode === "details"}
                      disabled={!graphLoaded}
                      onChange={() => onCommunityLevelModeChange("details")}
                    />
                    <span>Detailed areas</span>
                  </label>
                ) : null}
              </section>
            ) : null}
            <label className="check-row">
              <input
                type="checkbox"
                checked={showIsolatedCommunities}
                disabled={!graphLoaded || (!showIsolatedCommunities && hiddenIsolatedCommunityCount === 0)}
                onChange={(event) => onShowIsolatedCommunitiesChange(event.target.checked)}
              />
              <span>
                Show isolated communities
                {hiddenIsolatedCommunityCount > 0 ? ` (${hiddenIsolatedCommunityCount})` : ""}
              </span>
            </label>
          </>
        ) : null}
        <button className="secondary-button" type="button" onClick={onResetFilters} disabled={!graphLoaded}>
          Reset filters
        </button>
        {hiddenNodes.length > 0 ? (
          <section className="hidden-node-picker">
            <div className="filter-title">Hidden nodes</div>
            <div className="hidden-node-list">
              {hiddenNodes.map((node) => (
                <button
                  className="hidden-node-row"
                  type="button"
                  key={node.id}
                  title={`Show ${node.label}`}
                  onClick={() => onShowHiddenNode(node.id)}
                >
                  <Eye size={13} />
                  <span className="hidden-node-copy">
                    <strong>{node.label}</strong>
                    <small>{node.meta ? `${node.type} / ${node.meta}` : node.type}</small>
                  </span>
                </button>
              ))}
            </div>
            {hiddenNodes.length > 1 ? (
              <button className="secondary-button" type="button" onClick={onShowAllHiddenNodes}>
                Show all hidden ({hiddenNodes.length})
              </button>
            ) : null}
          </section>
        ) : null}
      </section>
    </aside>
  );
}
