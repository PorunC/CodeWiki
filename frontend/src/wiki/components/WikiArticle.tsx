import { BookOpenText } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type RefObject } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import type { SourceRef, WikiPageRecord } from "../../api/types";
import { wikiMarkdownComponents } from "../markdown/MarkdownComponents";
import { repairConjoinedFenceHeadings } from "../markdown/normalize";
import {
  extractRelevantSourceFilesSection,
  formatSourceRef,
  stripMarkdownSourcesSection
} from "../markdown/sections";
import { openSourceInGraph } from "../sourceNavigation";
import type { RelatedWikiPage } from "../types";

export function WikiArticle({
  articleRef,
  page,
  relatedPages,
  onSelectPage
}: {
  articleRef: RefObject<HTMLElement | null>;
  page: WikiPageRecord;
  relatedPages: RelatedWikiPage[];
  onSelectPage: (slug: string) => void;
}) {
  const markdownRef = useRef<HTMLDivElement | null>(null);
  const [headings, setHeadings] = useState<WikiHeading[]>([]);
  const [activeHeadingId, setActiveHeadingId] = useState<string | null>(null);
  const repairedMarkdown = useMemo(
    () => repairConjoinedFenceHeadings(page.markdown),
    [page.markdown]
  );
  const articleContent = useMemo(
    () => extractRelevantSourceFilesSection(stripMarkdownSourcesSection(repairedMarkdown)),
    [repairedMarkdown]
  );
  const labels = useMemo(() => wikiArticleLabels(page.language_code), [page.language_code]);
  const sourceGroups = useMemo(() => groupSourceRefs(page.source_refs), [page.source_refs]);
  const components = useMemo(
    () => wikiMarkdownComponents(onSelectPage),
    [onSelectPage]
  );

  useEffect(() => {
    const markdownElement = markdownRef.current;
    if (!markdownElement) {
      setHeadings([]);
      setActiveHeadingId(null);
      return;
    }

    const headingElements = Array.from(
      markdownElement.querySelectorAll<HTMLHeadingElement>("h2, h3")
    );
    const nextHeadings = headingElements.map((heading, index) => ({
      element: heading,
      id: headingId(page.slug, heading.textContent ?? "", index, headingElements),
      level: Number(heading.tagName.slice(1)),
      title: (heading.textContent ?? "").trim() || `Section ${index + 1}`
    }));
    nextHeadings.forEach(({ element, id }) => {
      element.id = id;
    });
    setHeadings(
      nextHeadings.map(({ id, level, title }) => ({
        id,
        level,
        title
      }))
    );
    setActiveHeadingId(nextHeadings[0]?.id ?? null);

    const scrollRoot = markdownElement.closest(".assistant-rail");
    const updateActiveHeading = () => {
      const threshold =
        scrollRoot instanceof HTMLElement
          ? scrollRoot.getBoundingClientRect().top + 28
          : 28;
      let nextActiveId = nextHeadings[0]?.id ?? null;
      for (const heading of nextHeadings) {
        if (heading.element.getBoundingClientRect().top <= threshold) {
          nextActiveId = heading.id;
        } else {
          break;
        }
      }
      setActiveHeadingId(nextActiveId);
    };

    updateActiveHeading();
    const scrollTarget = scrollRoot instanceof HTMLElement ? scrollRoot : window;
    scrollTarget.addEventListener("scroll", updateActiveHeading, { passive: true });
    window.addEventListener("resize", updateActiveHeading);
    return () => {
      scrollTarget.removeEventListener("scroll", updateActiveHeading);
      window.removeEventListener("resize", updateActiveHeading);
    };
  }, [repairedMarkdown, page.slug]);

  const handleHeadingSelect = useCallback((headingIdValue: string) => {
    const heading = document.getElementById(headingIdValue);
    if (!heading) {
      return;
    }
    heading.scrollIntoView({ behavior: "smooth", block: "start" });
    setActiveHeadingId(headingIdValue);
  }, []);

  return (
    <div className={`wiki-reader${headings.length > 0 ? " has-outline" : ""}`}>
      <article ref={articleRef} className="wiki-article">
        <div className="wiki-article-meta">
          <span className={page.status === "generated" ? "is-generated" : "is-draft"}>
            {page.status}
          </span>
          <span>{page.source_refs.length} {labels.sourcesMeta}</span>
          <span>{page.graph_refs.length} graph refs</span>
        </div>

        <div ref={markdownRef} className="wiki-markdown">
          <ReactMarkdown components={components} remarkPlugins={[remarkGfm]}>
            {articleContent.titleMarkdown}
          </ReactMarkdown>
          {articleContent.relevantFiles.length > 0 ? (
            <details className="wiki-relevant-files">
              <summary>{labels.relevantSourceFiles}</summary>
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

        {sourceGroups.length > 0 ? (
          <details className="wiki-source-list" open={page.source_refs.length <= 6}>
            <summary>
              <BookOpenText size={14} />
              <span>{labels.sources}</span>
              <strong>
                {page.source_refs.length} ranges / {sourceGroups.length} files
              </strong>
            </summary>
            <div className="wiki-source-groups">
              {sourceGroups.map((group) => (
                <section key={group.filePath} className="wiki-source-group">
                  <h4>
                    <span>{group.filePath}</span>
                    <strong>{group.refs.length}</strong>
                  </h4>
                  <div className="wiki-source-ranges">
                    {group.refs.map((source) => (
                      <button
                        key={`${source.file_path}:${source.start_line}:${source.end_line}`}
                        type="button"
                        title={`Open ${formatSourceRef(source)} in graph`}
                        onClick={() => openSourceInGraph(page.repo_id, source)}
                      >
                        {source.citation_id ? <span>{source.citation_id}</span> : null}
                        L{source.start_line}-L{source.end_line}
                      </button>
                    ))}
                  </div>
                </section>
              ))}
            </div>
          </details>
        ) : null}
      </article>

      {headings.length > 0 ? (
        <aside className="wiki-page-outline" aria-label="Current page navigation">
          <strong>On this page</strong>
          <nav className="wiki-page-outline-nav">
            {headings.map((heading) => (
              <button
                key={heading.id}
                className={activeHeadingId === heading.id ? "is-active" : undefined}
                style={{ paddingLeft: 10 + (heading.level - 2) * 14 }}
                type="button"
                aria-current={activeHeadingId === heading.id ? "location" : undefined}
                onClick={() => handleHeadingSelect(heading.id)}
              >
                {heading.title}
              </button>
            ))}
          </nav>
        </aside>
      ) : null}
    </div>
  );
}

type WikiHeading = {
  id: string;
  level: number;
  title: string;
};

function headingId(
  pageSlug: string,
  title: string,
  currentIndex: number,
  headingElements: HTMLHeadingElement[]
): string {
  const base = slugifyHeading(title) || "section";
  let duplicateIndex = 0;
  for (let index = 0; index < currentIndex; index += 1) {
    if ((slugifyHeading(headingElements[index].textContent ?? "") || "section") === base) {
      duplicateIndex += 1;
    }
  }
  return `wiki-${pageSlug}-${base}${duplicateIndex > 0 ? `-${duplicateIndex + 1}` : ""}`;
}

function slugifyHeading(title: string): string {
  return title
    .normalize("NFKC")
    .trim()
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, "-")
    .replace(/^-+|-+$/g, "");
}

type SourceGroup = {
  filePath: string;
  refs: SourceRef[];
};

function wikiArticleLabels(languageCode: string) {
  if (languageCode.toLowerCase().startsWith("zh")) {
    return {
      relevantSourceFiles: "相关源文件",
      sources: "来源",
      sourcesMeta: "条来源"
    };
  }
  return {
    relevantSourceFiles: "Relevant source files",
    sources: "Sources",
    sourcesMeta: "sources"
  };
}

function groupSourceRefs(sourceRefs: SourceRef[]): SourceGroup[] {
  const groups = new Map<string, SourceRef[]>();
  sourceRefs.forEach((sourceRef) => {
    const group = groups.get(sourceRef.file_path) ?? [];
    group.push(sourceRef);
    groups.set(sourceRef.file_path, group);
  });
  return Array.from(groups, ([filePath, refs]) => ({
    filePath,
    refs: refs
      .slice()
      .sort((left, right) => left.start_line - right.start_line || left.end_line - right.end_line)
  }));
}
