import { BookOpenText, FileText, RefreshCw } from "lucide-react";
import { useEffect, useId, useMemo, useState } from "react";
import ReactMarkdown, { type Components } from "react-markdown";

import {
  getRepos,
  getRepoWiki,
  type RepoSummary,
  type SourceRef,
  type WikiCatalogItem,
  type WikiPageRecord,
  type WikiResponse
} from "../api/client";

const markdownComponents: Components = {
  a({ href, children, ...props }) {
    if (href === "source-link") {
      return <>{children}</>;
    }
    return (
      <a href={href} {...props}>
        {children}
      </a>
    );
  },
  code({ className, children, ...props }) {
    const language = /language-(\w+)/.exec(className ?? "")?.[1];
    const code = String(children).replace(/\n$/, "");
    if (language === "mermaid") {
      return <MermaidBlock chart={code} />;
    }
    return (
      <code className={className} {...props}>
        {children}
      </code>
    );
  }
};

let mermaidInitialized = false;
let mermaidPromise: Promise<typeof import("mermaid").default> | null = null;

export function WikiPage({
  selectedRepoId,
  onRepoChange,
  isActiveSection
}: {
  selectedRepoId: string;
  onRepoChange: (repoId: string) => void;
  isActiveSection: boolean;
}) {
  const [repos, setRepos] = useState<RepoSummary[]>([]);
  const [wiki, setWiki] = useState<WikiResponse | null>(null);
  const [selectedSlug, setSelectedSlug] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [repoError, setRepoError] = useState<string | null>(null);
  const [refreshNonce, setRefreshNonce] = useState(0);

  useEffect(() => {
    let cancelled = false;
    getRepos()
      .then((repoList) => {
        if (cancelled) {
          return;
        }
        setRepos(repoList);
        setRepoError(null);
        if (!selectedRepoId && repoList[0]) {
          onRepoChange(repoList[0].id);
        }
      })
      .catch((apiError: unknown) => {
        if (!cancelled) {
          setRepoError(apiError instanceof Error ? apiError.message : "Failed to load repositories");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [onRepoChange, selectedRepoId]);

  useEffect(() => {
    if (!selectedRepoId) {
      setWiki(null);
      setSelectedSlug(null);
      return;
    }

    let cancelled = false;
    setLoading(true);
    setError(null);
    getRepoWiki(selectedRepoId)
      .then((response) => {
        if (cancelled) {
          return;
        }
        setWiki(response);
        setSelectedSlug((current) => {
          if (current && response.pages.some((page) => page.slug === current)) {
            return current;
          }
          return response.items[0]?.slug ?? response.pages[0]?.slug ?? null;
        });
      })
      .catch((apiError: unknown) => {
        if (!cancelled) {
          setWiki(null);
          setSelectedSlug(null);
          setError(apiError instanceof Error ? apiError.message : "Failed to load wiki");
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
  }, [refreshNonce, selectedRepoId]);

  const pageBySlug = useMemo(
    () => new Map((wiki?.pages ?? []).map((page) => [page.slug, page])),
    [wiki?.pages]
  );
  const selectedPage = selectedSlug ? pageBySlug.get(selectedSlug) ?? null : null;
  const generatedCount = wiki?.pages.filter((page) => page.status === "generated").length ?? 0;
  const selectedRepo = useMemo(
    () => repos.find((repo) => repo.id === selectedRepoId) ?? null,
    [repos, selectedRepoId]
  );

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
          onClick={() => setRefreshNonce((nonce) => nonce + 1)}
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
            <CatalogItems
              items={wiki.items}
              pageBySlug={pageBySlug}
              selectedSlug={selectedSlug}
              onSelect={setSelectedSlug}
            />
          </nav>

          {selectedPage ? <WikiArticle page={selectedPage} /> : null}
        </div>
      ) : null}
    </section>
  );
}

function CatalogItems({
  items,
  pageBySlug,
  selectedSlug,
  onSelect,
  depth = 0
}: {
  items: WikiCatalogItem[];
  pageBySlug: Map<string, WikiPageRecord>;
  selectedSlug: string | null;
  onSelect: (slug: string) => void;
  depth?: number;
}) {
  return (
    <div className="wiki-catalog-level">
      {items.map((item) => {
        const page = pageBySlug.get(item.slug);
        const children = item.children ?? [];
        return (
          <div key={item.slug} className="wiki-catalog-group">
            <button
              className={`wiki-catalog-item${selectedSlug === item.slug ? " is-active" : ""}`}
              style={{ paddingLeft: 8 + depth * 14 }}
              type="button"
              onClick={() => onSelect(item.slug)}
            >
              <FileText size={13} />
              <span>{item.title}</span>
              <strong className={page?.status === "generated" ? "is-generated" : "is-draft"}>
                {page?.status ?? "missing"}
              </strong>
            </button>
            {children.length > 0 ? (
              <CatalogItems
                items={children}
                pageBySlug={pageBySlug}
                selectedSlug={selectedSlug}
                onSelect={onSelect}
                depth={depth + 1}
              />
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

function WikiArticle({ page }: { page: WikiPageRecord }) {
  const markdown = useMemo(() => stripMarkdownSourcesSection(page.markdown), [page.markdown]);

  return (
    <article className="wiki-article">
      <div className="wiki-article-meta">
        <span className={page.status === "generated" ? "is-generated" : "is-draft"}>
          {page.status}
        </span>
        <span>{page.source_refs.length} sources</span>
        <span>{page.graph_refs.length} graph refs</span>
      </div>

      <div className="wiki-markdown">
        <ReactMarkdown components={markdownComponents}>{markdown}</ReactMarkdown>
      </div>

      {page.source_refs.length > 0 ? (
        <div className="wiki-source-list">
          <h3>
            <BookOpenText size={14} />
            Sources
          </h3>
          {page.source_refs.slice(0, 12).map((source) => (
            <button
              key={`${source.file_path}:${source.start_line}:${source.end_line}`}
              type="button"
              title="Open source in graph"
              onClick={() => openSourceInGraph(page.repo_id, source)}
            >
              {formatSourceRef(source)}
            </button>
          ))}
        </div>
      ) : null}
    </article>
  );
}

function MermaidBlock({ chart }: { chart: string }) {
  const reactId = useId();
  const diagramId = useMemo(
    () => `wiki-mermaid-${reactId.replace(/[^a-zA-Z0-9_-]/g, "")}-${hashString(chart)}`,
    [chart, reactId]
  );
  const [svg, setSvg] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setSvg("");
    setError(null);
    loadMermaid()
      .then((mermaidApi) => {
        if (!mermaidInitialized) {
          mermaidApi.initialize({
            startOnLoad: false,
            securityLevel: "strict",
            theme: "dark",
            themeVariables: {
              background: "#101111",
              primaryColor: "#1a1b1a",
              primaryBorderColor: "#d4a574",
              primaryTextColor: "#f5f0eb",
              lineColor: "#d4a574",
              secondaryColor: "#132224",
              tertiaryColor: "#0b0c0c"
            }
          });
          mermaidInitialized = true;
        }
        return mermaidApi.render(diagramId, chart);
      })
      .then((result) => {
        if (!cancelled) {
          setSvg(result.svg);
        }
      })
      .catch((renderError: unknown) => {
        if (!cancelled) {
          setError(renderError instanceof Error ? renderError.message : "Failed to render Mermaid diagram");
        }
      });

    return () => {
      cancelled = true;
    };
  }, [chart, diagramId]);

  if (error) {
    return (
      <div className="mermaid-block is-error">
        <strong>Mermaid render failed</strong>
        <pre>{chart}</pre>
      </div>
    );
  }

  if (!svg) {
    return <div className="mermaid-block is-loading">Rendering diagram...</div>;
  }

  return <div className="mermaid-block" dangerouslySetInnerHTML={{ __html: svg }} />;
}

function loadMermaid(): Promise<typeof import("mermaid").default> {
  mermaidPromise ??= import("mermaid").then((module) => module.default);
  return mermaidPromise;
}

function hashString(value: string): string {
  let hash = 0;
  for (let index = 0; index < value.length; index += 1) {
    hash = (hash * 31 + value.charCodeAt(index)) >>> 0;
  }
  return hash.toString(36);
}

function stripMarkdownSourcesSection(markdown: string): string {
  const lines = markdown.split(/\r?\n/);
  let inFence = false;
  let sourcesHeadingIndex = -1;

  lines.forEach((line, index) => {
    if (line.trimStart().startsWith("```")) {
      inFence = !inFence;
      return;
    }
    if (!inFence && /^#{2,6}\s+Sources\s*$/i.test(line.trim())) {
      sourcesHeadingIndex = index;
    }
  });

  if (sourcesHeadingIndex < 0) {
    return markdown;
  }

  return lines.slice(0, sourcesHeadingIndex).join("\n").trimEnd();
}

function formatSourceRef(source: SourceRef): string {
  return `${source.file_path}:L${source.start_line}-L${source.end_line}`;
}

function openSourceInGraph(repoId: string, source: SourceRef) {
  window.dispatchEvent(
    new CustomEvent("codewiki:open-source-ref", {
      detail: {
        repoId,
        filePath: source.file_path,
        startLine: source.start_line,
        endLine: source.end_line
      }
    })
  );
  if (window.location.hash !== "#graph") {
    window.location.hash = "graph";
  }
}
