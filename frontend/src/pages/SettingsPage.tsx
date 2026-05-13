import { RefreshCw, ServerCog } from "lucide-react";
import { useEffect, useState } from "react";

import { getHealth } from "../api/repos";
import { getLlmModels } from "../api/settings";
import type { LlmModelsResponse } from "../api/types";
import { useRepos } from "../hooks/useRepos";

export function SettingsPage({
  selectedRepoId,
  onRepoChange,
  isActiveSection
}: {
  selectedRepoId: string;
  onRepoChange: (repoId: string) => void;
  isActiveSection: boolean;
}) {
  const { repos, selectedRepo, error: repoError } = useRepos({ selectedRepoId, onRepoChange });
  const [models, setModels] = useState<LlmModelsResponse | null>(null);
  const [health, setHealth] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    Promise.all([getLlmModels(), getHealth()])
      .then(([modelData, healthData]) => {
        if (cancelled) {
          return;
        }
        setModels(modelData);
        setHealth(healthData.status);
      })
      .catch((apiError: unknown) => {
        if (!cancelled) {
          setError(apiError instanceof Error ? apiError.message : "Failed to load settings");
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [reloadToken]);

  return (
    <section id="settings" className={`side-panel ops-page${isActiveSection ? " is-nav-target" : ""}`}>
      <header className="ops-header">
        <div>
          <span className="eyebrow">Settings</span>
          <h2>Runtime settings</h2>
        </div>
        <button
          className="icon-button"
          type="button"
          title="Refresh settings"
          aria-label="Refresh settings"
          disabled={loading}
          onClick={() => setReloadToken((value) => value + 1)}
        >
          <RefreshCw size={15} />
        </button>
      </header>

      <div className="ops-toolbar">
        <label className="field">
          <span>Repository</span>
          <select value={selectedRepoId} onChange={(event) => onRepoChange(event.target.value)}>
            {repos.length === 0 ? <option value="">No repositories</option> : null}
            {repos.map((repo) => (
              <option key={repo.id} value={repo.id}>
                {repo.name}
              </option>
            ))}
          </select>
        </label>
        {selectedRepo ? <div className="ops-path">{selectedRepo.path}</div> : null}
      </div>

      <div className="ops-summary">
        <div>
          <span>API</span>
          <strong>{health || "-"}</strong>
        </div>
        <div>
          <span>Mode</span>
          <strong>{models?.mode ?? "-"}</strong>
        </div>
        <div>
          <span>Provider</span>
          <strong>{providerLabel(models?.base_url)}</strong>
        </div>
      </div>

      {loading ? <div className="ops-state">Loading settings...</div> : null}
      {!loading && repoError ? <div className="ops-state is-error">{repoError}</div> : null}
      {!loading && error ? <div className="ops-state is-error">{error}</div> : null}

      {models ? (
        <div className="settings-grid">
          <section className="settings-section">
            <header>
              <ServerCog size={16} />
              <h3>LLM routing</h3>
            </header>
            <dl>
              <div>
                <dt>Mode</dt>
                <dd>{models.mode}</dd>
              </div>
              <div>
                <dt>Base URL</dt>
                <dd className="ops-mono">{models.base_url || "default provider endpoint"}</dd>
              </div>
              <div>
                <dt>Small model</dt>
                <dd className="ops-mono">{models.small_model}</dd>
              </div>
              <div>
                <dt>Large model</dt>
                <dd className="ops-mono">{models.large_model}</dd>
              </div>
              <div>
                <dt>Catalog</dt>
                <dd className="ops-mono">{models.catalog_model}</dd>
              </div>
              <div>
                <dt>Community naming</dt>
                <dd className="ops-mono">{models.community_model}</dd>
              </div>
              <div>
                <dt>Wiki pages</dt>
                <dd className="ops-mono">{models.page_model}</dd>
              </div>
              <div>
                <dt>QA</dt>
                <dd className="ops-mono">{models.qa_model}</dd>
              </div>
              <div>
                <dt>Embedding model</dt>
                <dd className="ops-mono">{models.embedding_model}</dd>
              </div>
            </dl>
          </section>
        </div>
      ) : null}
    </section>
  );
}

function providerLabel(baseUrl?: string): string {
  if (!baseUrl) {
    return "default";
  }
  try {
    return new URL(baseUrl).host;
  } catch {
    return "custom";
  }
}
