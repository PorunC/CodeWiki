import { ExternalLink, Plus, RefreshCw, Search, Trash2 } from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";

import { createRepo, deleteRepo } from "../api/repos";
import type { RepoSummary } from "../api/types";
import { useRepos } from "../hooks/useRepos";
import { fuzzySearch } from "../search/fuzzy";
import type { WorkspaceSection } from "../App";

export function ReposPage({
  selectedRepoId,
  onRepoChange,
  onOpenRepo,
  isActiveSection
}: {
  selectedRepoId: string;
  onRepoChange: (repoId: string) => void;
  onOpenRepo: (repoId: string, section: WorkspaceSection) => void;
  isActiveSection: boolean;
}) {
  const { repos, loading, error: repoError, refresh } = useRepos({
    selectedRepoId,
    onRepoChange,
    autoSelect: false
  });
  const [path, setPath] = useState("");
  const [name, setName] = useState("");
  const [query, setQuery] = useState("");
  const [task, setTask] = useState<"create" | "delete" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const filteredRepos = useMemo(() => filterRepos(repos, query), [query, repos]);
  const selectedRepo = repos.find((repo) => repo.id === selectedRepoId) ?? null;

  const handleCreate = async (event: FormEvent) => {
    event.preventDefault();
    const trimmedPath = path.trim();
    if (!trimmedPath || task) {
      return;
    }
    setTask("create");
    setError(null);
    try {
      const repo = await createRepo({
        path: trimmedPath,
        name: name.trim() || undefined
      });
      setPath("");
      setName("");
      onRepoChange(repo.id);
      refresh();
    } catch (apiError) {
      setError(apiError instanceof Error ? apiError.message : "Repository create failed");
    } finally {
      setTask(null);
    }
  };

  const handleDelete = async (repo: RepoSummary) => {
    if (task) {
      return;
    }
    const confirmed = window.confirm(
      `Delete ${repo.name}? Stored analysis, wiki pages, chunks, embeddings, and run history for this repository will be removed. Source files on disk are not deleted.`
    );
    if (!confirmed) {
      return;
    }
    setTask("delete");
    setError(null);
    try {
      await deleteRepo(repo.id);
      if (selectedRepoId === repo.id) {
        const nextRepo = repos.find((candidate) => candidate.id !== repo.id) ?? null;
        onRepoChange(nextRepo?.id ?? "");
      }
      refresh();
    } catch (apiError) {
      setError(apiError instanceof Error ? apiError.message : "Repository delete failed");
    } finally {
      setTask(null);
    }
  };

  return (
    <section id="repos" className={`side-panel ops-page${isActiveSection ? " is-nav-target" : ""}`}>
      <header className="ops-header">
        <div>
          <span className="eyebrow">Repositories</span>
          <h2>Repository management</h2>
        </div>
        <button
          className="icon-button"
          type="button"
          title="Refresh repositories"
          aria-label="Refresh repositories"
          disabled={loading || task !== null}
          onClick={refresh}
        >
          <RefreshCw size={15} />
        </button>
      </header>

      <form className="repo-create-form" onSubmit={handleCreate}>
        <label className="field">
          <span>Path / Git URL</span>
          <input
            value={path}
            placeholder="/path/to/repository or https://github.com/org/repo.git"
            onChange={(event) => setPath(event.target.value)}
          />
        </label>
        <label className="field">
          <span>Name</span>
          <input
            value={name}
            placeholder="Optional display name"
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        <button className="secondary-button repo-create-button" type="submit" disabled={!path.trim() || task !== null}>
          <Plus size={14} />
          Add
        </button>
      </form>

      <div className="ops-summary">
        <div>
          <span>Total</span>
          <strong>{repos.length}</strong>
        </div>
        <div>
          <span>Selected</span>
          <strong>{selectedRepo?.name ?? "-"}</strong>
        </div>
        <div>
          <span>Source</span>
          <strong>{sourceTypeSummary(repos)}</strong>
        </div>
      </div>

      <div className="ops-toolbar repo-toolbar">
        <label className="ops-search">
          <Search size={14} />
          <input
            value={query}
            placeholder="Filter repositories"
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
      </div>

      {loading ? <div className="ops-state">Loading repositories...</div> : null}
      {!loading && repoError ? <div className="ops-state is-error">{repoError}</div> : null}
      {!loading && error ? <div className="ops-state is-error">{error}</div> : null}

      <div className="ops-table-wrap">
        <table className="ops-table repo-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Path</th>
              <th>Source</th>
              <th>Commit</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {filteredRepos.map((repo) => (
              <tr key={repo.id} className={repo.id === selectedRepoId ? "is-selected" : undefined}>
                <td>
                  <button className="repo-name-button" type="button" onClick={() => onRepoChange(repo.id)}>
                    {repo.name}
                  </button>
                </td>
                <td className="ops-mono">{repo.path}</td>
                <td>
                  <span className="ops-badge is-info">{repo.source_type}</span>
                </td>
                <td className="ops-mono">{repo.commit_hash || "-"}</td>
                <td>
                  <div className="repo-row-actions">
                    <button
                      className="icon-button"
                      type="button"
                      title={`Open ${repo.name} graph`}
                      aria-label={`Open ${repo.name} graph`}
                      onClick={() => onOpenRepo(repo.id, "graph")}
                    >
                      <ExternalLink size={14} />
                    </button>
                    <button
                      className="icon-button is-danger"
                      type="button"
                      title={`Delete ${repo.name}`}
                      aria-label={`Delete ${repo.name}`}
                      disabled={task !== null}
                      onClick={() => void handleDelete(repo)}
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
            {!loading && filteredRepos.length === 0 ? (
              <tr>
                <td colSpan={5}>
                  <span className="muted">No repositories found.</span>
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function filterRepos(repos: RepoSummary[], query: string): RepoSummary[] {
  return fuzzySearch(repos, query, ["name", "path", "source_type", "commit_hash"], {
    threshold: 0.36
  });
}

function sourceTypeSummary(repos: RepoSummary[]): string {
  const sourceTypes = new Set(repos.map((repo) => repo.source_type));
  return sourceTypes.size === 0 ? "-" : [...sourceTypes].sort().join(", ");
}
