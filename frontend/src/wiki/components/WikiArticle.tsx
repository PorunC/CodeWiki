import { BookOpenText } from "lucide-react";
import { useMemo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import type { WikiPageRecord } from "../../api/types";
import { wikiMarkdownComponents } from "../markdown/MarkdownComponents";
import {
  extractRelevantSourceFilesSection,
  formatSourceRef,
  stripMarkdownSourcesSection
} from "../markdown/sections";
import { openSourceInGraph } from "../sourceNavigation";
import type { RelatedWikiPage } from "../types";

export function WikiArticle({
  page,
  relatedPages,
  onSelectPage
}: {
  page: WikiPageRecord;
  relatedPages: RelatedWikiPage[];
  onSelectPage: (slug: string) => void;
}) {
  const articleContent = useMemo(
    () => extractRelevantSourceFilesSection(stripMarkdownSourcesSection(page.markdown)),
    [page.markdown]
  );
  const components = useMemo(
    () => wikiMarkdownComponents(onSelectPage),
    [onSelectPage]
  );

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
        <ReactMarkdown components={components} remarkPlugins={[remarkGfm]}>
          {articleContent.titleMarkdown}
        </ReactMarkdown>
        {articleContent.relevantFiles.length > 0 ? (
          <details className="wiki-relevant-files">
            <summary>Relevant source files</summary>
            <ul>
              {articleContent.relevantFiles.map((file) => (
                <li key={`${file.label}:${file.href}`}>
                  {file.href === "source-link" ? <span>{file.label}</span> : <a href={file.href}>{file.label}</a>}
                </li>
              ))}
            </ul>
          </details>
        ) : null}
        <ReactMarkdown components={components} remarkPlugins={[remarkGfm]}>
          {articleContent.bodyMarkdown}
        </ReactMarkdown>
      </div>

      {relatedPages.length > 0 ? (
        <div className="wiki-related-pages">
          <h3>See also</h3>
          {relatedPages.map((relatedPage) => (
            <button
              key={relatedPage.slug}
              type="button"
              onClick={() => onSelectPage(relatedPage.slug)}
            >
              <strong>{relatedPage.title}</strong>
              <span>{relatedPage.path}</span>
            </button>
          ))}
        </div>
      ) : null}

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
