import { FileCode2, Focus, Network } from "lucide-react";

import type { RepoSummary } from "../api/client";
import { ModeButton } from "./GraphControls";
import type { GraphViewMode } from "./graphModel";

export function GraphToolbar({
  repos,
  selectedRepo,
  selectedRepoId,
  repoLoading,
  viewMode,
  selectedFileId,
  selectedNodeId,
  graphStats,
  onRepoChange,
  onModeSelect
}: {
  repos: RepoSummary[];
  selectedRepo: RepoSummary | null;
  selectedRepoId: string;
  repoLoading: boolean;
  viewMode: GraphViewMode;
  selectedFileId: string | null;
  selectedNodeId: string | null;
  graphStats: string;
  onRepoChange: (repoId: string) => void;
  onModeSelect: (mode: GraphViewMode) => void;
}) {
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
        <div className="view-switcher" aria-label="Graph view mode">
          <ModeButton
            active={viewMode === "overview"}
            label="Overview"
            title="Overview"
            icon={<Network size={14} />}
            onClick={() => onModeSelect("overview")}
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
        </div>
        <div className="graph-counts" aria-live="polite">
          {graphStats}
        </div>
      </div>
    </div>
  );
}
