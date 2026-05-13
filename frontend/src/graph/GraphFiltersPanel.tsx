import { Eye, FolderTree } from "lucide-react";
import type { ReactNode } from "react";

import { FilterGroup } from "./GraphControls";
import { modeHint, type GraphViewMode } from "./graphModel";

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
  graphLoaded,
  hiddenNodes,
  onNodeTypeToggle,
  onEdgeTypeToggle,
  onShowInferredCallsChange,
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
  graphLoaded: boolean;
  hiddenNodes: HiddenVisualNodeOption[];
  onNodeTypeToggle: (type: string) => void;
  onEdgeTypeToggle: (type: string) => void;
  onShowInferredCallsChange: (show: boolean) => void;
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
