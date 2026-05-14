import { FileCode2, Focus, FolderOpen, Network, Play, RefreshCw, SlidersHorizontal } from "lucide-react";

import type { RepoSummary } from "../api/types";
import { ModeButton } from "./GraphControls";
import type { GraphDensityMode, GraphViewMode } from "./graphModel";

export function GraphToolbar({
  repos,
  selectedRepo,
  selectedRepoId,
  repoLoading,
  viewMode,
  densityMode,
  drilldownAvailable,
  selectedFileId,
  selectedNodeId,
  graphStats,
  analysisTask,
  onRepoChange,
  onModeSelect,
  onDensityModeToggle,
  onFullAnalyze,
  onIncrementalUpdate
}: {
  repos: RepoSummary[];
  selectedRepo: RepoSummary | null;
  selectedRepoId: string;
  repoLoading: boolean;
  viewMode: GraphViewMode;
  densityMode: GraphDensityMode;
  drilldownAvailable: boolean;
  selectedFileId: string | null;
  selectedNodeId: string | null;
  graphStats: string;
  analysisTask: "analyze" | "update" | null;
  onRepoChange: (repoId: string) => void;
  onModeSelect: (mode: GraphViewMode) => void;
  onDensityModeToggle: () => void;
  onFullAnalyze: () => void;
  onIncrementalUpdate: () => void;
}) {
  const analysisDisabled = repoLoading || !selectedRepoId || analysisTask !== null;
  return (
    <div className="graph-toolbar">
      <label className="field">
        <span>Repository</span>
        <select
          value={selectedRepoId}
          onChange={(event) => onRepoChange(event.target.value)}
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
        <div className="analysis-actions" aria-label="Repository analysis actions">
          <button
            className="secondary-button graph-action-button"
            type="button"
            disabled={analysisDisabled}
            onClick={onFullAnalyze}
          >
            <Play size={14} />
            {analysisTask === "analyze" ? "Analyzing" : "Analyze"}
          </button>
          <button
            className="secondary-button graph-action-button"
            type="button"
            disabled={analysisDisabled}
            onClick={onIncrementalUpdate}
          >
            <RefreshCw size={14} />
            {analysisTask === "update" ? "Updating" : "Update"}
          </button>
        </div>
        <div className="view-switcher" aria-label="Graph view mode">
          <ModeButton
            active={viewMode === "overview"}
            label="Overview"
            title="Overview"
            icon={<Network size={14} />}
            onClick={() => onModeSelect("overview")}
          />
          <ModeButton
            active={viewMode === "drilldown"}
            label="Drill"
            title="Container drill-down"
            icon={<FolderOpen size={14} />}
            onClick={() => onModeSelect("drilldown")}
            disabled={!drilldownAvailable}
          />
          <ModeButton
            active={viewMode === "file"}
            label="File"
            title="File detail"
            icon={<FileCode2 size={14} />}
            onClick={() => onModeSelect("file")}
            disabled={!selectedFileId}
          />
          <ModeButton
            active={viewMode === "focus"}
            label="Focus"
            title="Focus neighborhood"
            icon={<Focus size={14} />}
            onClick={() => onModeSelect("focus")}
            disabled={!selectedNodeId}
          />
          <ModeButton
            active={densityMode === "full"}
            label={densityMode === "full" ? "Full" : "Readable"}
            title="Toggle graph density"
            icon={<SlidersHorizontal size={14} />}
            onClick={onDensityModeToggle}
          />
        </div>
        <div className="graph-counts" aria-live="polite">
          {graphStats}
        </div>
      </div>
    </div>
  );
}
