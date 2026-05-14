import { FileText, RefreshCw, RotateCw } from "lucide-react";
import { useCallback, useMemo, useState } from "react";

import { generateWikiPages, regenerateWikiPage } from "../api/wiki";
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
  const [generationTask, setGenerationTask] = useState<"pages" | "page" | null>(null);
  const [generationMessage, setGenerationMessage] = useState<string | null>(null);
  const [generationError, setGenerationError] = useState<string | null>(null);
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
  const isGenerating = generationTask !== null;
  const generationDisabled = !selectedRepoId || loading || generationTask !== null;
  const currentPageDisabled = generationDisabled || !selectedSlug;

  const handleGeneratePages = useCallback(async () => {
    if (!selectedRepoId || generationTask) {
      return;
    }
    setGenerationTask("pages");
    setGenerationError(null);
    setGenerationMessage("Generating wiki pages...");
    try {
      const result = await generateWikiPages(selectedRepoId);
      const invalidCount = result.pages.filter((page) => page.validation_errors.length > 0).length;
      const suffix = invalidCount ? ` ${invalidCount} pages need review.` : "";
      setGenerationMessage(`Generated ${result.page_count} wiki pages.${suffix}`);
      refresh();
    } catch (apiError) {
      setGenerationError(apiError instanceof Error ? apiError.message : "Wiki page generation failed");
      setGenerationMessage(null);
    } finally {
      setGenerationTask(null);
    }
  }, [generationTask, refresh, selectedRepoId]);

  const handleRegeneratePage = useCallback(async () => {
    if (!selectedRepoId || !selectedSlug || generationTask) {
      return;
    }
    setGenerationTask("page");
    setGenerationError(null);
    setGenerationMessage(`Regenerating ${selectedSlug}...`);
    try {
      const result = await regenerateWikiPage(selectedRepoId, selectedSlug);
      const suffix = result.validation_errors.length ? " Validation needs review." : "";
      setGenerationMessage(`Regenerated ${result.title}.${suffix}`);
      refresh();
    } catch (apiError) {
      setGenerationError(apiError instanceof Error ? apiError.message : "Wiki page regeneration failed");
      setGenerationMessage(null);
    } finally {
      setGenerationTask(null);
    }
  }, [generationTask, refresh, selectedRepoId, selectedSlug]);

  return (
    <section id="wiki" className={`side-panel wiki-panel${isActiveSection ? " is-nav-target" : ""}`}>
      <header className="wiki-header">
        <div>
          <span className="eyebrow">Wiki</span>
          <h2>{wiki?.catalog?.title ?? "Documentation"}</h2>
        </div>
        <div className="wiki-header-actions">
          <button
            className="secondary-button wiki-action-button"
            type="button"
            title="Generate all wiki pages"
            disabled={generationDisabled}
            onClick={handleGeneratePages}
          >
            <FileText className={generationTask === "pages" ? "wiki-spin-icon" : undefined} size={14} />
            {generationTask === "pages" ? "Generating" : "Generate pages"}
          </button>
          <button
            className="icon-button"
            type="button"
            title="Regenerate current page"
            aria-label="Regenerate current page"
            disabled={currentPageDisabled}
            onClick={handleRegeneratePage}
          >
            <RotateCw className={generationTask === "page" ? "wiki-spin-icon" : undefined} size={15} />
          </button>
          <button
            className="icon-button"
            type="button"
            title="Refresh wiki"
            aria-label="Refresh wiki"
            disabled={!selectedRepoId || loading || generationTask !== null}
            onClick={refresh}
          >
            <RefreshCw size={15} />
          </button>
        </div>
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
      {generationMessage ? (
        <div
          className={`wiki-state${isGenerating ? " is-loading" : ""}`}
          role={isGenerating ? "status" : undefined}
          aria-live="polite"
          aria-busy={isGenerating || undefined}
        >
          {isGenerating ? <RefreshCw className="wiki-spin-icon" size={15} aria-hidden="true" /> : null}
          <span>{generationMessage}</span>
        </div>
      ) : null}
      {generationError ? <div className="wiki-state is-error">{generationError}</div> : null}
      {!loading && wiki && wiki.pages.length === 0 ? (
        <div className="wiki-state">No generated wiki pages yet.</div>
      ) : null}

      {wiki ? (
        <div className={`wiki-browser${isGenerating ? " is-generating" : ""}`} aria-busy={isGenerating || undefined}>
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
