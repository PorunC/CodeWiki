import { FolderTree } from "lucide-react";

import { FilterGroup } from "./GraphControls";
import { modeHint, type GraphViewMode } from "./graphModel";

export function GraphFiltersPanel({
  viewMode,
  nodeTypes,
  edgeTypes,
  selectedNodeTypes,
  selectedEdgeTypes,
  showInferredCalls,
  graphLoaded,
  hiddenCount,
  onNodeTypeToggle,
  onEdgeTypeToggle,
  onShowInferredCallsChange,
  onResetFilters,
  onShowHiddenNodes
}: {
  viewMode: GraphViewMode;
  nodeTypes: string[];
  edgeTypes: string[];
  selectedNodeTypes: Set<string>;
  selectedEdgeTypes: Set<string>;
  showInferredCalls: boolean;
  graphLoaded: boolean;
  hiddenCount: number;
  onNodeTypeToggle: (type: string) => void;
  onEdgeTypeToggle: (type: string) => void;
  onShowInferredCallsChange: (show: boolean) => void;
  onResetFilters: () => void;
  onShowHiddenNodes: () => void;
}) {
  return (
    <aside className="graph-filters">
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
      {hiddenCount > 0 ? (
        <button className="secondary-button" type="button" onClick={onShowHiddenNodes}>
          Show hidden nodes ({hiddenCount})
        </button>
      ) : null}
    </aside>
  );
}
