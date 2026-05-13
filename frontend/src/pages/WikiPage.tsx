import { RefreshCw } from "lucide-react";
import { useMemo } from "react";

import { useRepos } from "../hooks/useRepos";
import { WikiArticle } from "../wiki/components/WikiArticle";
import { WikiCatalog } from "../wiki/components/WikiCatalog";
import { useWikiData } from "../wiki/hooks/useWikiData";
import { relatedPagesForPage } from "../wiki/relatedPages";

export function WikiPage({
  selectedRepoId,
  onRepoChange,
  isActiveSection
}: {
  selectedRepoId: string;
  onRepoChange: (repoId: string) => void;
  isActiveSection: boolean;
}) {
  const { repos, selectedRepo, error: repoError } = useRepos({ selectedRepoId, onRepoChange });
  const {
    wiki,
    selectedSlug,
    selectedPage,
    pageBySlug,
    loading,
    error,
    refresh,
    setSelectedSlug
  } = useWikiData(selectedRepoId);
  const relatedPages = useMemo(
    () => (wiki && selectedPage ? relatedPagesForPage(wiki.items, pageBySlug, selectedPage.slug) : []),
    [pageBySlug, selectedPage, wiki]
  );
  const generatedCount = wiki?.pages.filter((page) => page.status === "generated").length ?? 0;

  return (
    <section id="wiki" className={`side-panel wiki-panel${isActiveSection ? " is-nav-target" : ""}`}>
      <header className="wiki-header">
        <div>
          <span className="eyebrow">Wiki</span>
          <h2>{wiki?.catalog?.title ?? "Documentation"}</h2>
        </div>
        <button
          className="icon-button"
          type="button"
          title="Refresh wiki"
          aria-label="Refresh wiki"
          disabled={!selectedRepoId || loading}
          onClick={refresh}
        >
          <RefreshCw size={15} />
        </button>
      </header>

      <div className="wiki-repo-bar">
        <label className="field">
          <span>Repository</span>
          <select
            value={selectedRepoId}
            onChange={(event) => onRepoChange(event.target.value)}
            aria-label="Repository for wiki"
          >
            {repos.length === 0 ? <option value="">No repositories</option> : null}
            {repos.map((repo) => (
              <option key={repo.id} value={repo.id}>
                {repo.name}
              </option>
            ))}
          </select>
        </label>
        {selectedRepo ? <div className="wiki-repo-path">{selectedRepo.path}</div> : null}
      </div>

      <div className="wiki-summary">
        <div>
          <span>Pages</span>
          <strong>{wiki?.pages.length ?? 0}</strong>
        </div>
        <div>
          <span>Generated</span>
          <strong>{generatedCount}</strong>
        </div>
        <div>
          <span>Sources</span>
          <strong>{selectedPage?.source_refs.length ?? 0}</strong>
        </div>
      </div>

      {loading ? <div className="wiki-state">Loading wiki...</div> : null}
      {!loading && !selectedRepoId ? <div className="wiki-state">Select a repository first.</div> : null}
      {!loading && repoError ? <div className="wiki-state is-error">{repoError}</div> : null}
      {!loading && error ? <div className="wiki-state is-error">{error}</div> : null}
      {!loading && wiki && wiki.pages.length === 0 ? (
        <div className="wiki-state">No generated wiki pages yet.</div>
      ) : null}

      {wiki ? (
        <div className="wiki-browser">
          <nav className="wiki-catalog" aria-label="Wiki catalog">
            <WikiCatalog
              items={wiki.items}
              pageBySlug={pageBySlug}
              selectedSlug={selectedSlug}
              onSelect={setSelectedSlug}
            />
          </nav>

          {selectedPage ? (
            <WikiArticle page={selectedPage} relatedPages={relatedPages} onSelectPage={setSelectedSlug} />
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
