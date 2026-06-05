import type { WikiCatalogItem, WikiPageRecord, WikiResponse } from "../../api/types";
import {
  catalogItemTitle,
  catalogSlug,
  firstPageSlugFromItems,
  sortCatalogItems
} from "../catalog";
import { repairConjoinedFenceHeadings } from "../markdown/normalize";
import { stripMarkdownSourcesSection } from "../markdown/sections";
import { relatedPagesForPage } from "../relatedPages";
import { escapeHtml, renderMarkdownToHtml } from "./markdown";
import { buildStoredZip, type ZipEntry } from "./zip";

export type WikiExportOptions = {
  wiki: WikiResponse;
  repoName?: string;
  languageCode: string;
  languageLabel: string;
};

type CatalogRow = {
  title: string;
  depth: number;
  targetSlug: string | null;
  status: string;
  searchText: string;
};

export function downloadInteractiveWikiHtml(options: WikiExportOptions): void {
  const blob = new Blob([buildInteractiveWikiHtml(options)], { type: "text/html;charset=utf-8" });
  downloadBlob(blob, `${exportBaseName(options)}.html`);
}

export function downloadObsidianVault(options: WikiExportOptions): void {
  const archive = buildObsidianVaultArchive(options);
  const blob = new Blob([archive], { type: "application/zip" });
  downloadBlob(blob, `${exportBaseName(options)}-obsidian-vault.zip`);
}

export function buildInteractiveWikiHtml(options: WikiExportOptions): string {
  const pageBySlug = new Map(options.wiki.pages.map((page) => [page.slug, page]));
  const rows = catalogRows(options.wiki.items, pageBySlug);
  const rowsWithLoosePages = appendLoosePageRows(rows, options.wiki.pages);
  const firstSlug =
    firstPageSlugFromItems(options.wiki.items, pageBySlug) ?? options.wiki.pages[0]?.slug ?? null;
  const pages = options.wiki.pages.map((page) => {
    const markdown = repairConjoinedFenceHeadings(page.markdown);
    return {
      slug: page.slug,
      title: page.title,
      status: page.status,
      sourceCount: page.source_refs.length,
      graphCount: page.graph_refs.length,
      html: renderMarkdownToHtml(stripMarkdownSourcesSection(markdown), htmlLinkRenderer),
      searchText: normalizeSearchText(`${page.title} ${markdown}`),
      sources: page.source_refs.map((source) => ({
        label: `${source.file_path}:L${source.start_line}-L${source.end_line}`,
        href: source.source_url ?? null
      })),
      relatedPages: relatedPagesForPage(options.wiki.items, pageBySlug, page.slug)
    };
  });
  const pagePayload = serializeForScript({
    firstSlug,
    pages
  });
  const title = options.wiki.catalog?.title ?? `${options.repoName ?? "Repository"} Wiki`;

  return `<!doctype html>
<html lang="${escapeHtml(options.languageCode)}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>${escapeHtml(title)}</title>
  <style>${standaloneStyles()}</style>
</head>
<body>
  <div class="shell">
    <aside class="sidebar">
      <div class="sidebar-header">
        <p>${escapeHtml(options.repoName ?? "Repository")}</p>
        <h1>${escapeHtml(title)}</h1>
        <span>${escapeHtml(options.languageLabel)}</span>
      </div>
      <label class="search">
        <span>Search</span>
        <input type="search" placeholder="Find a page" data-search>
      </label>
      <nav aria-label="Wiki catalog" data-catalog>
        ${rowsWithLoosePages.map(renderCatalogRow).join("\n")}
      </nav>
    </aside>
    <main class="main">
      <header class="page-header">
        <div>
          <p data-page-meta></p>
          <h2 data-page-title></h2>
        </div>
      </header>
      <article class="article" data-article></article>
      <section class="related" data-related hidden>
        <h3>See also</h3>
        <div data-related-links></div>
      </section>
      <section class="sources" data-source-section hidden>
        <h3>Sources</h3>
        <div data-source-list></div>
      </section>
    </main>
  </div>
  <script id="wiki-data" type="application/json">${pagePayload}</script>
  <script>${standaloneScript()}</script>
</body>
</html>`;
}

export function buildObsidianVaultArchive(options: WikiExportOptions): Uint8Array {
  const pageBySlug = new Map(options.wiki.pages.map((page) => [page.slug, page]));
  const pathBySlug = vaultPaths(options.wiki.items, options.wiki.pages);
  const vaultName = `${exportBaseName(options)}-vault`;
  const entries: ZipEntry[] = [
    {
      path: `${vaultName}/.obsidian/app.json`,
      data: JSON.stringify(
        {
          showInlineTitle: true
        },
        null,
        2
      )
    },
    {
      path: `${vaultName}/Home.md`,
      data: buildVaultHome(options, pathBySlug, pageBySlug)
    }
  ];

  for (const page of options.wiki.pages) {
    const vaultPath = pathBySlug.get(page.slug) ?? sanitizeVaultPath(page.slug);
    entries.push({
      path: `${vaultName}/${vaultPath}.md`,
      data: rewriteMarkdownForVault(repairConjoinedFenceHeadings(page.markdown), pathBySlug)
    });
  }

  return buildStoredZip(entries);
}

function catalogRows(
  items: WikiCatalogItem[],
  pageBySlug: Map<string, WikiPageRecord>,
  depth = 0
): CatalogRow[] {
  const rows: CatalogRow[] = [];
  for (const item of sortCatalogItems(items)) {
    const slug = catalogSlug(item);
    const title = catalogItemTitle(item);
    const page = pageBySlug.get(slug);
    const children = item.children ?? [];
    const targetSlug = page?.slug ?? firstPageSlugFromItems(children, pageBySlug);
    rows.push({
      title,
      depth,
      targetSlug,
      status: page?.status ?? (children.length > 0 ? "group" : "missing"),
      searchText: normalizeSearchText(`${title} ${page?.markdown ?? ""}`)
    });
    rows.push(...catalogRows(children, pageBySlug, depth + 1));
  }
  return rows;
}

function appendLoosePageRows(rows: CatalogRow[], pages: WikiPageRecord[]): CatalogRow[] {
  const knownSlugs = new Set(rows.map((row) => row.targetSlug).filter((slug): slug is string => Boolean(slug)));
  const looseRows = pages
    .filter((page) => !knownSlugs.has(page.slug))
    .map((page) => ({
      title: page.title,
      depth: 0,
      targetSlug: page.slug,
      status: page.status,
      searchText: normalizeSearchText(`${page.title} ${page.markdown}`)
    }));
  return [...rows, ...looseRows];
}

function renderCatalogRow(row: CatalogRow): string {
  const disabled = row.targetSlug ? "" : " disabled";
  const target = row.targetSlug ? ` data-page-slug="${escapeHtml(row.targetSlug)}"` : "";
  return `<button class="catalog-row" style="--depth:${row.depth}" data-search-text="${escapeHtml(row.searchText)}"${target}${disabled}>
    <span>${escapeHtml(row.title)}</span>
    <strong>${escapeHtml(row.status)}</strong>
  </button>`;
}

function htmlLinkRenderer(label: string, href: string): string {
  if (href === "source-link") {
    return `<span class="source-label">${label}</span>`;
  }
  const internalSlug = wikiPageSlugFromHref(href);
  if (internalSlug) {
    return `<a href="#page=${encodeURIComponent(internalSlug)}" data-page-slug="${escapeHtml(internalSlug)}">${label}</a>`;
  }
  const escapedHref = escapeHtml(href);
  const external = href.startsWith("http://") || href.startsWith("https://");
  return `<a href="${escapedHref}"${external ? ' target="_blank" rel="noreferrer"' : ""}>${label}</a>`;
}

function vaultPaths(items: WikiCatalogItem[], pages: WikiPageRecord[]): Map<string, string> {
  const pathBySlug = new Map<string, string>();
  const usedPaths = new Set<string>();

  const visit = (catalogItems: WikiCatalogItem[]) => {
    for (const item of sortCatalogItems(catalogItems)) {
      const slug = catalogSlug(item);
      if (pages.some((page) => page.slug === slug)) {
        pathBySlug.set(slug, uniqueVaultPath(sanitizeVaultPath(item.path ?? slug), usedPaths));
      }
      visit(item.children ?? []);
    }
  };

  visit(items);
  for (const page of pages) {
    if (!pathBySlug.has(page.slug)) {
      pathBySlug.set(page.slug, uniqueVaultPath(sanitizeVaultPath(page.slug), usedPaths));
    }
  }
  return pathBySlug;
}

function buildVaultHome(
  options: WikiExportOptions,
  pathBySlug: Map<string, string>,
  pageBySlug: Map<string, WikiPageRecord>
): string {
  const title = options.wiki.catalog?.title ?? `${options.repoName ?? "Repository"} Wiki`;
  const lines = [
    `# ${title}`,
    "",
    `- Repository: ${options.repoName ?? "Repository"}`,
    `- Language: ${options.languageLabel}`,
    `- Pages: ${options.wiki.pages.length}`,
    "",
    "## Catalog",
    "",
    ...vaultCatalogLines(options.wiki.items, pathBySlug, pageBySlug)
  ];
  const loosePages = options.wiki.pages.filter((page) => !pathBySlugHasCatalogPath(options.wiki.items, page.slug));
  if (loosePages.length > 0) {
    lines.push("", "## Other Pages", "");
    for (const page of loosePages) {
      lines.push(`- [[${pathBySlug.get(page.slug) ?? sanitizeVaultPath(page.slug)}|${page.title}]]`);
    }
  }
  return `${lines.join("\n").trimEnd()}\n`;
}

function vaultCatalogLines(
  items: WikiCatalogItem[],
  pathBySlug: Map<string, string>,
  pageBySlug: Map<string, WikiPageRecord>,
  depth = 0
): string[] {
  const lines: string[] = [];
  for (const item of sortCatalogItems(items)) {
    const slug = catalogSlug(item);
    const title = catalogItemTitle(item);
    const page = pageBySlug.get(slug);
    const indent = "  ".repeat(depth);
    const label = page ? `[[${pathBySlug.get(slug) ?? sanitizeVaultPath(slug)}|${title}]]` : title;
    lines.push(`${indent}- ${label}`);
    lines.push(...vaultCatalogLines(item.children ?? [], pathBySlug, pageBySlug, depth + 1));
  }
  return lines;
}

function rewriteMarkdownForVault(markdown: string, pathBySlug: Map<string, string>): string {
  return markdown.replace(/(?<!!)\[([^\]]+)]\(([^)]+)\)/g, (match, label: string, href: string) => {
    if (href === "source-link") {
      return label;
    }
    const internalSlug = wikiPageSlugFromHref(href);
    if (!internalSlug) {
      return match;
    }
    const vaultPath = pathBySlug.get(internalSlug);
    return vaultPath ? `[[${vaultPath}|${label}]]` : match;
  });
}

function pathBySlugHasCatalogPath(items: WikiCatalogItem[], slug: string): boolean {
  for (const item of items) {
    if (catalogSlug(item) === slug) {
      return true;
    }
    if (pathBySlugHasCatalogPath(item.children ?? [], slug)) {
      return true;
    }
  }
  return false;
}

function uniqueVaultPath(path: string, usedPaths: Set<string>): string {
  let candidate = path;
  let suffix = 2;
  while (usedPaths.has(candidate.toLowerCase())) {
    candidate = `${path}-${suffix}`;
    suffix += 1;
  }
  usedPaths.add(candidate.toLowerCase());
  return candidate;
}

function sanitizeVaultPath(path: string): string {
  const segments = path
    .split("/")
    .map((segment) => sanitizePathSegment(segment))
    .filter(Boolean);
  return segments.join("/") || "page";
}

function sanitizePathSegment(segment: string): string {
  return segment
    .trim()
    .replace(/[<>:"\\|?*]/g, "-")
    .replace(/\s+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "") || "page";
}

function exportBaseName(options: WikiExportOptions): string {
  return sanitizeFileName(`${options.repoName ?? "wiki"}-${options.languageCode}-wiki`);
}

function sanitizeFileName(value: string): string {
  return value
    .trim()
    .replace(/[<>:"/\\|?*]/g, "-")
    .replace(/\s+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "") || "wiki";
}

function serializeForScript(value: unknown): string {
  return JSON.stringify(value).replaceAll("<", "\\u003c");
}

function normalizeSearchText(value: string): string {
  return value.toLocaleLowerCase();
}

function wikiPageSlugFromHref(href: string): string | null {
  if (href.startsWith("wiki-page:")) {
    return href.slice("wiki-page:".length);
  }
  const wikiPathMatch = /^\/wiki\/[^/]+\/([^/#?]+)$/.exec(href);
  return wikiPathMatch?.[1] ?? null;
}

function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

function standaloneStyles(): string {
  return `
:root{color-scheme:dark;--root:#090a0a;--panel:#101111;--elevated:#171918;--border:rgba(212,165,116,.16);--border-strong:rgba(212,165,116,.34);--accent:#d4a574;--accent-strong:#e8c49a;--text:#f5f0eb;--muted:#a39787;--quiet:#6b5f53;--blue:#9cc2db;font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
*{box-sizing:border-box}html,body{margin:0;min-height:100%;background:var(--root);color:var(--text)}body{line-height:1.55}
.shell{display:grid;grid-template-columns:minmax(260px,340px) minmax(0,1fr);min-height:100vh}
.sidebar{background:rgba(16,17,17,.96);border-right:1px solid var(--border);display:grid;align-content:start;gap:16px;padding:20px}
.sidebar-header{display:grid;gap:4px}.sidebar-header p{color:var(--quiet);font-size:12px;font-weight:800;margin:0;text-transform:uppercase}.sidebar-header h1{font-size:22px;line-height:1.15;margin:0}.sidebar-header span{color:var(--blue);font-size:12px}
.search{display:grid;gap:6px}.search span{color:var(--quiet);font-size:11px;font-weight:800;text-transform:uppercase}.search input{background:rgba(255,255,255,.035);border:1px solid var(--border);border-radius:8px;color:var(--text);min-height:38px;padding:0 11px}
nav{display:grid;gap:3px}.catalog-row{align-items:center;background:transparent;border:1px solid transparent;border-radius:7px;color:var(--muted);cursor:pointer;display:flex;gap:8px;min-height:36px;padding:7px 8px 7px calc(8px + var(--depth)*16px);text-align:left}.catalog-row:hover,.catalog-row.is-active{background:rgba(212,165,116,.08);border-color:var(--border);color:var(--text)}.catalog-row[disabled]{cursor:default;opacity:.6}.catalog-row span{flex:1;font-weight:700;min-width:0}.catalog-row strong{border:1px solid var(--border);border-radius:999px;color:var(--quiet);font-size:10px;padding:3px 6px;text-transform:uppercase}
.main{display:grid;align-content:start;gap:16px;min-width:0;padding:28px clamp(18px,4vw,44px)}.page-header{border-bottom:1px solid var(--border);padding-bottom:16px}.page-header p{color:var(--blue);font-size:12px;font-weight:800;margin:0 0 6px;text-transform:uppercase}.page-header h2{font-size:28px;line-height:1.1;margin:0}
.article{color:var(--muted);font-size:15px;line-height:1.72;max-width:960px;overflow-wrap:anywhere}.article>:first-child{margin-top:0}.article h1,.article h2,.article h3,.article h4{color:var(--text);letter-spacing:0}.article h1{font-size:28px}.article h2{border-top:1px solid var(--border);font-size:21px;margin-top:1.4em;padding-top:18px}.article h3{font-size:17px}.article p,.article ul,.article ol,.article blockquote,.article pre,.article table{margin:0 0 14px}.article ul,.article ol{padding-left:24px}.article code{background:rgba(212,165,116,.08);border:1px solid var(--border);border-radius:5px;color:var(--accent-strong);font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:.92em;padding:1px 5px}.article pre{background:#0b0c0c;border:1px solid var(--border);border-radius:8px;overflow:auto;padding:12px}.article pre code{background:transparent;border:0;color:var(--text);display:block;padding:0;white-space:pre}.article blockquote{border-left:3px solid var(--border-strong);padding-left:12px}.article table{background:rgba(255,255,255,.01);border-collapse:collapse;display:block;font-size:.92em;overflow:auto;width:100%}.article th,.article td{border:1px solid var(--border);padding:8px 10px;text-align:left;vertical-align:top}.article th{background:rgba(255,255,255,.04);color:var(--text)}.article a{color:var(--accent-strong);text-decoration:underline;text-underline-offset:3px}.source-label{color:var(--accent-strong)}
.related,.sources{border-top:1px solid var(--border);display:grid;gap:10px;max-width:960px;padding-top:16px}.related h3,.sources h3{color:var(--quiet);font-size:12px;margin:0;text-transform:uppercase}.related div,.sources div{display:flex;flex-wrap:wrap;gap:8px}.related button,.sources a,.sources span{background:rgba(255,255,255,.018);border:1px solid var(--border);border-radius:8px;color:var(--muted);padding:8px 10px}.related button{cursor:pointer}.related button:hover{border-color:var(--border-strong);color:var(--text)}.sources a{color:var(--accent-strong);text-decoration:none}
@media (max-width:820px){.shell{grid-template-columns:1fr}.sidebar{border-bottom:1px solid var(--border);border-right:0}.main{padding-top:20px}}
`;
}

function standaloneScript(): string {
  return `
(() => {
  const payload = JSON.parse(document.getElementById("wiki-data").textContent || "{}");
  const pages = payload.pages || [];
  const pageBySlug = new Map(pages.map((page) => [page.slug, page]));
  const article = document.querySelector("[data-article]");
  const title = document.querySelector("[data-page-title]");
  const meta = document.querySelector("[data-page-meta]");
  const sourceSection = document.querySelector("[data-source-section]");
  const sourceList = document.querySelector("[data-source-list]");
  const relatedSection = document.querySelector("[data-related]");
  const relatedLinks = document.querySelector("[data-related-links]");
  const search = document.querySelector("[data-search]");
  const catalogButtons = Array.from(document.querySelectorAll("[data-page-slug]")).filter((node) => node.tagName === "BUTTON");

  const activeSlugFromHash = () => {
    const hash = window.location.hash.replace(/^#/, "");
    return hash.startsWith("page=") ? decodeURIComponent(hash.slice("page=".length)) : null;
  };
  const setActivePage = (slug, updateHash = true) => {
    const page = pageBySlug.get(slug);
    if (!page || !article || !title || !meta || !sourceSection || !sourceList || !relatedSection || !relatedLinks) {
      return;
    }
    title.textContent = page.title;
    meta.textContent = page.status + " / " + page.sourceCount + " sources / " + page.graphCount + " graph refs";
    article.innerHTML = page.html;
    catalogButtons.forEach((button) => button.classList.toggle("is-active", button.dataset.pageSlug === slug));
    sourceList.innerHTML = page.sources
      .map((source) => source.href
        ? '<a href="' + escapeAttribute(source.href) + '" target="_blank" rel="noreferrer">' + escapeHtml(source.label) + '</a>'
        : '<span>' + escapeHtml(source.label) + '</span>')
      .join("");
    sourceSection.hidden = page.sources.length === 0;
    relatedLinks.innerHTML = page.relatedPages
      .map((related) => '<button type="button" data-page-slug="' + escapeAttribute(related.slug) + '">' + escapeHtml(related.title) + '</button>')
      .join("");
    relatedSection.hidden = page.relatedPages.length === 0;
    if (updateHash) {
      window.history.replaceState(null, "", "#page=" + encodeURIComponent(slug));
    }
  };
  const applySearch = () => {
    const query = String(search && search.value ? search.value : "").trim().toLocaleLowerCase();
    catalogButtons.forEach((button) => {
      button.hidden = Boolean(query) && !String(button.dataset.searchText || "").includes(query);
    });
  };
  const escapeHtml = (value) => String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
  const escapeAttribute = escapeHtml;

  document.addEventListener("click", (event) => {
    const target = event.target instanceof Element ? event.target.closest("[data-page-slug]") : null;
    if (!target) {
      return;
    }
    const slug = target.getAttribute("data-page-slug");
    if (!slug || !pageBySlug.has(slug)) {
      return;
    }
    event.preventDefault();
    setActivePage(slug);
  });
  if (search) {
    search.addEventListener("input", applySearch);
  }
  window.addEventListener("hashchange", () => {
    const slug = activeSlugFromHash();
    if (slug) {
      setActivePage(slug, false);
    }
  });
  setActivePage(activeSlugFromHash() || payload.firstSlug || (pages[0] && pages[0].slug), false);
})();
`;
}
