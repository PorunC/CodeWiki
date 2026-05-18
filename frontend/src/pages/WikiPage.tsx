import { Archive, Download, FileCode2, FileText, RefreshCw, RotateCw } from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type PointerEvent
} from "react";

import { generateWikiPages, regenerateWikiPage, updateWikiPages } from "../api/wiki";
import { useRepos } from "../hooks/useRepos";
import { WikiArticle } from "../wiki/components/WikiArticle";
import { WikiCatalog } from "../wiki/components/WikiCatalog";
import {
  downloadInteractiveWikiHtml,
  downloadObsidianVault
} from "../wiki/export";
import { useWikiData } from "../wiki/hooks/useWikiData";
import {
  clearCompletedWikiGenerationOperation,
  completeWikiGenerationOperation,
  startWikiGenerationOperation,
  useWikiGenerationOperation
} from "../wiki/hooks/useWikiGenerationOperation";
import { missingPageSlugsFromItems } from "../wiki/catalog";
import { relatedPagesForPage } from "../wiki/relatedPages";

const WIKI_CATALOG_WIDTH_KEY = "codewiki:wiki-catalog-width";
const WIKI_LANGUAGE_KEY = "codewiki:wiki-language";
const WIKI_CATALOG_DEFAULT_WIDTH = 300;
const WIKI_CATALOG_MIN_WIDTH = 220;
const WIKI_CATALOG_MAX_WIDTH = 560;
const WIKI_ARTICLE_MIN_WIDTH = 420;
const WIKI_CATALOG_RESPONSIVE_BREAKPOINT = 900;
const WIKI_OUTLINE_RESPONSIVE_BREAKPOINT = 1200;
const WIKI_OUTLINE_RESERVED_WIDTH = 236;
const WIKI_GENERATION_POLL_INTERVAL_MS = 3_000;
const WIKI_LANGUAGES = [
  { code: "en", label: "English" },
  { code: "zh", label: "中文" }
] as const;

type WikiLanguage = (typeof WIKI_LANGUAGES)[number]["code"];

function initialCatalogWidth(): number {
  if (typeof window === "undefined") {
    return WIKI_CATALOG_DEFAULT_WIDTH;
  }
  const storedWidth = Number(window.localStorage.getItem(WIKI_CATALOG_WIDTH_KEY));
  return Number.isFinite(storedWidth)
    ? clamp(storedWidth, WIKI_CATALOG_MIN_WIDTH, WIKI_CATALOG_MAX_WIDTH)
    : WIKI_CATALOG_DEFAULT_WIDTH;
}

function initialWikiLanguage(): WikiLanguage {
  if (typeof window === "undefined") {
    return "en";
  }
  const storedLanguage = window.localStorage.getItem(WIKI_LANGUAGE_KEY);
  return storedLanguage === "zh" ? "zh" : "en";
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

function generationStatusMessage(
  message: string | null,
  task: "pages" | "update" | "page" | null,
  status: "running" | "success" | "error" | null,
  missingPageCount: number
): string | null {
  if (!message) {
    return null;
  }
  if (missingPageCount === 0 || task === "page") {
    return message;
  }
  const suffix =
    status === "running"
      ? `${missingPageCount} wiki pages remaining.`
      : `${missingPageCount} wiki pages are still missing.`;
  return `${message} ${suffix}`;
}

function wikiPageUpdatedAfter(updatedAt: string | null, startedAt: number): boolean {
  if (!updatedAt) {
    return false;
  }
  const updatedAtTime = Date.parse(updatedAt);
  return Number.isFinite(updatedAtTime) && updatedAtTime >= startedAt;
}

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
  const browserRef = useRef<HTMLDivElement | null>(null);
  const articleRef = useRef<HTMLElement | null>(null);
  const dragStateRef = useRef<{ startX: number; startWidth: number } | null>(null);
  const exportMenuRef = useRef<HTMLDivElement | null>(null);
  const [catalogWidth, setCatalogWidth] = useState(initialCatalogWidth);
  const [selectedLanguage, setSelectedLanguage] = useState<WikiLanguage>(initialWikiLanguage);
  const [isResizingCatalog, setIsResizingCatalog] = useState(false);
  const [isExportMenuOpen, setIsExportMenuOpen] = useState(false);
  const [exportMessage, setExportMessage] = useState<string | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);
  const {
    wiki,
    selectedSlug,
    selectedPage,
    pageBySlug,
    loading,
    error,
    refresh,
    setSelectedSlug
  } = useWikiData(selectedRepoId, selectedLanguage);
  const generationOperation = useWikiGenerationOperation(selectedRepoId, selectedLanguage);
  const relatedPages = useMemo(
    () => (wiki && selectedPage ? relatedPagesForPage(wiki.items, pageBySlug, selectedPage.slug) : []),
    [pageBySlug, selectedPage, wiki]
  );
  const missingPageSlugs = useMemo(
    () => (wiki ? missingPageSlugsFromItems(wiki.items, pageBySlug) : []),
    [pageBySlug, wiki]
  );
  const generatedCount = wiki?.pages.filter((page) => page.status === "generated").length ?? 0;
  const isGenerating = generationOperation?.status === "running";
  const generationTask = isGenerating ? generationOperation.task : null;
  const generationMessage = generationStatusMessage(
    generationOperation?.message ?? null,
    generationOperation?.task ?? null,
    generationOperation?.status ?? null,
    missingPageSlugs.length
  );
  const generationError =
    generationOperation?.status === "error" ? generationOperation.error : null;
  const generationDisabled = !selectedRepoId || loading || isGenerating;
  const currentPageDisabled = generationDisabled || !selectedSlug;
  const exportDisabled = !wiki || wiki.pages.length === 0 || loading || isGenerating;
  const selectedLanguageLabel =
    WIKI_LANGUAGES.find((language) => language.code === selectedLanguage)?.label ?? "English";
  const refreshedGenerationIdsRef = useRef<Set<number>>(new Set());

  const scrollArticleToTop = useCallback(() => {
    window.requestAnimationFrame(() => {
      articleRef.current?.scrollIntoView({ block: "start" });
    });
  }, []);

  const handleSelectWikiPage = useCallback(
    (slug: string) => {
      setSelectedSlug(slug);
      scrollArticleToTop();
    },
    [scrollArticleToTop, setSelectedSlug]
  );

  const clampCatalogWidth = useCallback((width: number) => {
    const browserWidth = browserRef.current?.getBoundingClientRect().width ?? 0;
    const outlineReserve =
      window.innerWidth > WIKI_OUTLINE_RESPONSIVE_BREAKPOINT
        ? WIKI_OUTLINE_RESERVED_WIDTH
        : 0;
    const browserMax =
      browserWidth > 0
        ? Math.max(WIKI_CATALOG_MIN_WIDTH, browserWidth - WIKI_ARTICLE_MIN_WIDTH - outlineReserve - 8)
        : WIKI_CATALOG_MAX_WIDTH;
    return clamp(width, WIKI_CATALOG_MIN_WIDTH, Math.min(WIKI_CATALOG_MAX_WIDTH, browserMax));
  }, []);

  const handleCatalogResizeStart = useCallback(
    (event: PointerEvent<HTMLDivElement>) => {
      if (window.innerWidth <= WIKI_CATALOG_RESPONSIVE_BREAKPOINT) {
        return;
      }
      event.preventDefault();
      dragStateRef.current = {
        startX: event.clientX,
        startWidth: catalogWidth
      };
      setIsResizingCatalog(true);
    },
    [catalogWidth]
  );

  const handleCatalogResizeKeyDown = useCallback(
    (event: KeyboardEvent<HTMLDivElement>) => {
      const step = event.shiftKey ? 40 : 16;
      if (event.key === "ArrowLeft") {
        event.preventDefault();
        setCatalogWidth((current) => clampCatalogWidth(current - step));
      } else if (event.key === "ArrowRight") {
        event.preventDefault();
        setCatalogWidth((current) => clampCatalogWidth(current + step));
      } else if (event.key === "Home") {
        event.preventDefault();
        setCatalogWidth((current) => clampCatalogWidth(Math.min(current, WIKI_CATALOG_MIN_WIDTH)));
      } else if (event.key === "End") {
        event.preventDefault();
        setCatalogWidth((current) => clampCatalogWidth(Math.max(current, WIKI_CATALOG_MAX_WIDTH)));
      }
    },
    [clampCatalogWidth]
  );

  useEffect(() => {
    if (!isResizingCatalog) {
      return;
    }

    const handlePointerMove = (event: globalThis.PointerEvent) => {
      const dragState = dragStateRef.current;
      if (!dragState) {
        return;
      }
      setCatalogWidth(clampCatalogWidth(dragState.startWidth + event.clientX - dragState.startX));
    };
    const handlePointerEnd = () => {
      dragStateRef.current = null;
      setIsResizingCatalog(false);
    };

    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", handlePointerEnd);
    window.addEventListener("pointercancel", handlePointerEnd);
    return () => {
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", handlePointerEnd);
      window.removeEventListener("pointercancel", handlePointerEnd);
    };
  }, [clampCatalogWidth, isResizingCatalog]);

  useEffect(() => {
    const handleResize = () => {
      if (window.innerWidth <= WIKI_CATALOG_RESPONSIVE_BREAKPOINT) {
        return;
      }
      setCatalogWidth((current) => clampCatalogWidth(current));
    };

    handleResize();
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, [clampCatalogWidth]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    window.localStorage.setItem(WIKI_CATALOG_WIDTH_KEY, String(Math.round(catalogWidth)));
  }, [catalogWidth]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    window.localStorage.setItem(WIKI_LANGUAGE_KEY, selectedLanguage);
  }, [selectedLanguage]);

  useEffect(() => {
    setExportMessage(null);
    setExportError(null);
  }, [selectedLanguage]);

  useEffect(() => {
    if (!isGenerating) {
      return;
    }
    refresh();
    const intervalId = window.setInterval(refresh, WIKI_GENERATION_POLL_INTERVAL_MS);
    return () => window.clearInterval(intervalId);
  }, [isGenerating, refresh]);

  useEffect(() => {
    if (generationOperation?.status !== "success") {
      return;
    }
    if (refreshedGenerationIdsRef.current.has(generationOperation.operationId)) {
      return;
    }
    refreshedGenerationIdsRef.current.add(generationOperation.operationId);
    refresh();
  }, [generationOperation?.operationId, generationOperation?.status, refresh]);

  useEffect(() => {
    if (
      !generationOperation ||
      generationOperation.status !== "running" ||
      generationOperation.task !== "page"
    ) {
      return;
    }
    const targetSlug = generationOperation.targetSlug ?? selectedSlug;
    if (!targetSlug) {
      return;
    }
    const regeneratedPage = pageBySlug.get(targetSlug);
    if (!regeneratedPage || !wikiPageUpdatedAfter(regeneratedPage.updated_at, generationOperation.startedAt)) {
      return;
    }
    completeWikiGenerationOperation(
      selectedRepoId,
      selectedLanguage,
      generationOperation.operationId,
      `Regenerated ${regeneratedPage.title}.`
    );
  }, [generationOperation, pageBySlug, selectedLanguage, selectedRepoId, selectedSlug]);

  useEffect(() => {
    if (
      !generationOperation ||
      generationOperation.status !== "success" ||
      (generationOperation.task !== "page" && missingPageSlugs.length > 0)
    ) {
      return;
    }
    clearCompletedWikiGenerationOperation(selectedRepoId, selectedLanguage);
  }, [generationOperation, missingPageSlugs.length, selectedLanguage, selectedRepoId]);

  useEffect(() => {
    if (!isExportMenuOpen) {
      return;
    }

    const handlePointerDown = (event: globalThis.PointerEvent) => {
      if (event.target instanceof Node && !exportMenuRef.current?.contains(event.target)) {
        setIsExportMenuOpen(false);
      }
    };
    const handleKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") {
        setIsExportMenuOpen(false);
      }
    };

    window.addEventListener("pointerdown", handlePointerDown);
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("pointerdown", handlePointerDown);
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [isExportMenuOpen]);

  const handleGeneratePages = useCallback(() => {
    if (!selectedRepoId || isGenerating) {
      return;
    }
    void startWikiGenerationOperation({
      repoId: selectedRepoId,
      language: selectedLanguage,
      task: "pages",
      message: `Generating ${selectedLanguageLabel} wiki pages...`,
      run: () => generateWikiPages(selectedRepoId, selectedLanguage),
      successMessage: (result) => {
        const invalidCount = result.pages.filter((page) => page.validation_errors.length > 0).length;
        const suffix = invalidCount ? ` ${invalidCount} pages need review.` : "";
        return `Generated ${result.page_count} ${selectedLanguageLabel} wiki pages.${suffix}`;
      },
      errorMessage: "Wiki page generation failed"
    }).catch(() => undefined);
  }, [isGenerating, selectedLanguage, selectedLanguageLabel, selectedRepoId]);

  const handleUpdateWiki = useCallback(() => {
    if (!selectedRepoId || isGenerating) {
      return;
    }
    void startWikiGenerationOperation({
      repoId: selectedRepoId,
      language: selectedLanguage,
      task: "update",
      message: `Updating ${selectedLanguageLabel} wiki incrementally...`,
      run: () => updateWikiPages(selectedRepoId, selectedLanguage),
      successMessage: (result) => {
        const affectedFiles = result.incremental_update.affected_files.length;
        const updatedText =
          result.generated_count > 0
            ? `Updated ${result.generated_count} ${selectedLanguageLabel} wiki pages`
            : `No ${selectedLanguageLabel} wiki pages needed regeneration`;
        const fileText =
          affectedFiles > 0
            ? ` from ${affectedFiles} changed files.`
            : ". Source graph was already current.";
        const deletedText =
          result.deleted_page_count > 0 ? ` Removed ${result.deleted_page_count} obsolete pages.` : "";
        return `${updatedText}${fileText}${deletedText}`;
      },
      errorMessage: "Wiki incremental update failed"
    }).catch(() => undefined);
  }, [isGenerating, selectedLanguage, selectedLanguageLabel, selectedRepoId]);

  const handleRegeneratePage = useCallback(() => {
    if (!selectedRepoId || !selectedSlug || isGenerating) {
      return;
    }
    void startWikiGenerationOperation({
      repoId: selectedRepoId,
      language: selectedLanguage,
      task: "page",
      targetSlug: selectedSlug,
      message: `Regenerating ${selectedSlug}...`,
      run: () => regenerateWikiPage(selectedRepoId, selectedSlug, selectedLanguage),
      successMessage: (result) => {
        const suffix = result.validation_errors.length ? " Validation needs review." : "";
        return `Regenerated ${result.title}.${suffix}`;
      },
      errorMessage: "Wiki page regeneration failed"
    }).catch(() => undefined);
  }, [isGenerating, selectedLanguage, selectedRepoId, selectedSlug]);

  const handleExportHtml = useCallback(() => {
    if (!wiki || exportDisabled) {
      return;
    }
    try {
      downloadInteractiveWikiHtml({
        wiki,
        repoName: selectedRepo?.name,
        languageCode: selectedLanguage,
        languageLabel: selectedLanguageLabel
      });
      setExportError(null);
      setExportMessage(`Downloaded ${selectedLanguageLabel} interactive HTML export.`);
      setIsExportMenuOpen(false);
    } catch (exportFailure) {
      setExportError(exportFailure instanceof Error ? exportFailure.message : "HTML export failed");
      setExportMessage(null);
    }
  }, [exportDisabled, selectedLanguage, selectedLanguageLabel, selectedRepo?.name, wiki]);

  const handleExportObsidian = useCallback(() => {
    if (!wiki || exportDisabled) {
      return;
    }
    try {
      downloadObsidianVault({
        wiki,
        repoName: selectedRepo?.name,
        languageCode: selectedLanguage,
        languageLabel: selectedLanguageLabel
      });
      setExportError(null);
      setExportMessage(`Downloaded ${selectedLanguageLabel} Obsidian vault export.`);
      setIsExportMenuOpen(false);
    } catch (exportFailure) {
      setExportError(exportFailure instanceof Error ? exportFailure.message : "Obsidian export failed");
      setExportMessage(null);
    }
  }, [exportDisabled, selectedLanguage, selectedLanguageLabel, selectedRepo?.name, wiki]);

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
            className="secondary-button wiki-action-button"
            type="button"
            title="Incrementally update wiki from repository changes"
            disabled={generationDisabled}
            onClick={handleUpdateWiki}
          >
            <RefreshCw className={generationTask === "update" ? "wiki-spin-icon" : undefined} size={14} />
            {generationTask === "update" ? "Updating" : "Update wiki"}
          </button>
          <div className="wiki-export-control" ref={exportMenuRef}>
            <button
              className="secondary-button wiki-action-button"
              type="button"
              title="Export wiki"
              aria-haspopup="menu"
              aria-expanded={isExportMenuOpen}
              disabled={exportDisabled}
              onClick={() => setIsExportMenuOpen((current) => !current)}
            >
              <Download size={14} />
              Export
            </button>
            {isExportMenuOpen ? (
              <div className="wiki-export-menu" role="menu">
                <button type="button" role="menuitem" onClick={handleExportHtml}>
                  <FileCode2 size={14} />
                  Interactive HTML
                </button>
                <button type="button" role="menuitem" onClick={handleExportObsidian}>
                  <Archive size={14} />
                  Obsidian vault
                </button>
              </div>
            ) : null}
          </div>
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
            disabled={!selectedRepoId || loading || isGenerating}
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
      {exportMessage ? <div className="wiki-state">{exportMessage}</div> : null}
      {exportError ? <div className="wiki-state is-error">{exportError}</div> : null}
      {!loading && wiki && wiki.pages.length === 0 ? (
        <div className="wiki-state">No generated {selectedLanguageLabel} wiki pages yet.</div>
      ) : null}

      {wiki ? (
        <div
          ref={browserRef}
          className={[
            "wiki-browser",
            isGenerating ? "is-generating" : "",
            isResizingCatalog ? "is-resizing-catalog" : ""
          ]
            .filter(Boolean)
            .join(" ")}
          style={{ "--wiki-catalog-width": `${catalogWidth}px` } as CSSProperties}
          aria-busy={isGenerating || undefined}
        >
          <nav className="wiki-catalog" aria-label="Wiki catalog">
            <div className="wiki-catalog-language">
              <div className="wiki-language-toggle" role="group" aria-label="Wiki language">
                {WIKI_LANGUAGES.map((language) => (
                  <button
                    key={language.code}
                    className={`wiki-language-button${selectedLanguage === language.code ? " is-active" : ""}`}
                    type="button"
                    aria-pressed={selectedLanguage === language.code}
                    disabled={isGenerating}
                    onClick={() => setSelectedLanguage(language.code)}
                  >
                    {language.label}
                  </button>
                ))}
              </div>
            </div>
            <WikiCatalog
              items={wiki.items}
              pageBySlug={pageBySlug}
              selectedSlug={selectedSlug}
              onSelect={handleSelectWikiPage}
            />
          </nav>
          <div
            className="wiki-catalog-resizer"
            role="separator"
            aria-label="Resize wiki catalog"
            aria-orientation="vertical"
            aria-valuemax={WIKI_CATALOG_MAX_WIDTH}
            aria-valuemin={WIKI_CATALOG_MIN_WIDTH}
            aria-valuenow={Math.round(catalogWidth)}
            tabIndex={0}
            title="Resize wiki catalog"
            onKeyDown={handleCatalogResizeKeyDown}
            onPointerDown={handleCatalogResizeStart}
          />

          {selectedPage ? (
            <WikiArticle
              articleRef={articleRef}
              page={selectedPage}
              relatedPages={relatedPages}
              onSelectPage={handleSelectWikiPage}
            />
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
