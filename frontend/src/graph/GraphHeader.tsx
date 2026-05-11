import { RefreshCcw } from "lucide-react";

export function GraphHeader({
  selectedRepoId,
  graphLoading,
  onRefresh
}: {
  selectedRepoId: string;
  graphLoading: boolean;
  onRefresh: () => void;
}) {
  return (
    <header className="graph-header">
      <div>
        <span className="eyebrow">Graph</span>
        <h1>Code Structure</h1>
      </div>
      <button
        className="icon-button"
        type="button"
        onClick={onRefresh}
        disabled={!selectedRepoId || graphLoading}
        title="Refresh graph"
        aria-label="Refresh graph"
      >
        <RefreshCcw size={16} />
      </button>
    </header>
  );
}
