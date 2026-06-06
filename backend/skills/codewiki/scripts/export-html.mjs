#!/usr/bin/env node
import { execFileSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";

main();

function main() {
  const { positional, options } = parseArgs(process.argv.slice(2));
  if (options.help || positional.length < 1) {
    printHelp();
    process.exit(positional.length < 1 && !options.help ? 1 : 0);
  }

  const [repo] = positional;
  const language = stringOption(options.language, "en");
  const output = resolve(stringOption(options.output, "codewiki-wiki.html"));
  const codewikiBin = stringOption(options["codewiki-bin"], "codewiki");
  const title = stringOption(options.title, null);

  const raw = execFileSync(
    codewikiBin,
    ["wiki", "list", repo, "--language", language, "--json"],
    { encoding: "utf8", maxBuffer: 64 * 1024 * 1024 },
  );
  const payload = JSON.parse(raw);
  const pages = arrayValue(payload.pages);
  const orderedPages = orderedWikiPages(pages, payload.catalog);
  const html = renderHtml({
    title: title || stringValue(payload.catalog?.title) || "CodeWiki",
    repoId: stringValue(payload.repo_id) || repo,
    language,
    pages: orderedPages,
  });

  mkdirSync(dirname(output), { recursive: true });
  writeFileSync(output, html, "utf8");
  process.stdout.write(
    `${JSON.stringify(
      {
        status: "written",
        output,
        page_count: orderedPages.length,
        language_code: language,
      },
      null,
      2,
    )}\n`,
  );
}

function orderedWikiPages(pages, catalog) {
  const bySlug = new Map(
    pages
      .map((page) => [stringValue(page.slug), page])
      .filter(([slug]) => typeof slug === "string"),
  );
  const orderedSlugs = [];
  for (const item of arrayValue(catalog?.structure?.items)) {
    collectCatalogSlugs(item, orderedSlugs);
  }
  const result = [];
  const seen = new Set();
  for (const slug of orderedSlugs) {
    const page = bySlug.get(slug);
    if (page && !seen.has(slug)) {
      result.push(page);
      seen.add(slug);
    }
  }
  for (const page of pages) {
    const slug = stringValue(page.slug);
    if (slug && !seen.has(slug)) {
      result.push(page);
      seen.add(slug);
    }
  }
  return result;
}

function collectCatalogSlugs(item, slugs) {
  const slug = stringValue(item?.slug);
  if (slug) {
    slugs.push(slug);
  }
  for (const child of arrayValue(item?.children)) {
    collectCatalogSlugs(child, slugs);
  }
}

function renderHtml({ title, repoId, language, pages }) {
  const renderedPages = pages.map((page) => renderPage(page)).join("\n");
  const toc = pages
    .map((page) => {
      const slug = pageSlug(page);
      return `<li><a href="#page-${escapeAttr(slug)}">${escapeHtml(pageTitle(page))}</a></li>`;
    })
    .join("\n");
  return `<!doctype html>
<html lang="${escapeAttr(language)}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>${escapeHtml(title)}</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f7f7f4;
      --surface: #ffffff;
      --text: #202124;
      --muted: #646a73;
      --border: #d9ded8;
      --accent: #176b87;
      --code: #f1f4f3;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 16px/1.6 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    header {
      padding: 32px min(6vw, 64px) 24px;
      background: #12343b;
      color: white;
    }
    header p { margin: 6px 0 0; color: #d4e2e5; }
    main {
      display: grid;
      grid-template-columns: minmax(180px, 280px) minmax(0, 1fr);
      gap: 28px;
      padding: 28px min(6vw, 64px) 56px;
    }
    nav {
      position: sticky;
      top: 18px;
      align-self: start;
      padding: 18px;
      border: 1px solid var(--border);
      background: var(--surface);
      border-radius: 8px;
    }
    nav h2 { margin-top: 0; font-size: 15px; }
    nav ol { margin: 0; padding-left: 20px; }
    nav a, article a { color: var(--accent); }
    article {
      margin-bottom: 28px;
      padding: 28px;
      border: 1px solid var(--border);
      background: var(--surface);
      border-radius: 8px;
    }
    article h1, article h2, article h3 { line-height: 1.25; }
    article h1 { margin-top: 0; font-size: 28px; }
    pre, code {
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace;
      background: var(--code);
    }
    code { padding: 0.1em 0.3em; border-radius: 4px; }
    pre {
      overflow-x: auto;
      padding: 14px;
      border-radius: 8px;
    }
    pre code { padding: 0; background: transparent; }
    table {
      width: 100%;
      border-collapse: collapse;
      margin: 16px 0;
      font-size: 14px;
    }
    th, td {
      border: 1px solid var(--border);
      padding: 8px 10px;
      vertical-align: top;
    }
    th { background: #eef3f1; text-align: left; }
    .citation {
      margin-left: 0.2em;
      font-size: 0.85em;
      text-decoration: none;
    }
    .sources {
      margin-top: 24px;
      padding-top: 16px;
      border-top: 1px solid var(--border);
      color: var(--muted);
      font-size: 14px;
    }
    .sources ol { padding-left: 22px; }
    @media (max-width: 820px) {
      main { display: block; padding: 20px; }
      nav { position: static; margin-bottom: 20px; }
      article { padding: 20px; }
    }
  </style>
</head>
<body>
  <header>
    <h1>${escapeHtml(title)}</h1>
    <p>Repository: ${escapeHtml(repoId)} | Language: ${escapeHtml(language)} | Pages: ${pages.length}</p>
  </header>
  <main>
    <nav aria-label="Wiki pages">
      <h2>Pages</h2>
      <ol>
        ${toc}
      </ol>
    </nav>
    <section>
      ${renderedPages}
    </section>
  </main>
</body>
</html>
`;
}

function renderPage(page) {
  const slug = pageSlug(page);
  const title = pageTitle(page);
  const markdown = stringValue(page.markdown) || `# ${title}`;
  return `<article id="page-${escapeAttr(slug)}">
${renderMarkdown(markdown, slug)}
${renderSources(page, slug)}
</article>`;
}

function renderSources(page, slug) {
  const refs = arrayValue(page.source_refs);
  if (!refs.length) {
    return "";
  }
  const items = refs
    .map((ref) => {
      const citationId = stringValue(ref.citation_id) || "S?";
      const path = stringValue(ref.file_path) || "unknown";
      const start = numberValue(ref.start_line);
      const end = numberValue(ref.end_line);
      const range = start && end ? `:${start}-${end}` : "";
      return `<li id="${escapeAttr(sourceId(slug, citationId))}"><strong>${escapeHtml(
        citationId,
      )}</strong> ${escapeHtml(path)}${escapeHtml(range)}</li>`;
    })
    .join("\n");
  return `<section class="sources">
  <h2>Sources</h2>
  <ol>${items}</ol>
</section>`;
}

function renderMarkdown(markdown, pageSlugValue) {
  const lines = markdown.replace(/\r\n/g, "\n").split("\n");
  const html = [];
  for (let index = 0; index < lines.length; ) {
    const line = lines[index];
    if (!line.trim()) {
      index += 1;
      continue;
    }
    if (/^```/.test(line.trim())) {
      const code = [];
      index += 1;
      while (index < lines.length && !/^```/.test(lines[index].trim())) {
        code.push(lines[index]);
        index += 1;
      }
      index += index < lines.length ? 1 : 0;
      html.push(`<pre><code>${escapeHtml(code.join("\n"))}</code></pre>`);
      continue;
    }
    const heading = /^(#{1,6})\s+(.+)$/.exec(line);
    if (heading) {
      const level = heading[1].length;
      const text = stripInlineMarkdown(heading[2]);
      html.push(
        `<h${level} id="${escapeAttr(slugify(`${pageSlugValue}-${text}`))}">${inlineHtml(
          heading[2],
          pageSlugValue,
        )}</h${level}>`,
      );
      index += 1;
      continue;
    }
    if (isTableStart(lines, index)) {
      const tableLines = [];
      while (index < lines.length && lines[index].includes("|")) {
        tableLines.push(lines[index]);
        index += 1;
      }
      html.push(renderTable(tableLines, pageSlugValue));
      continue;
    }
    if (/^\s*[-*]\s+/.test(line)) {
      const items = [];
      while (index < lines.length && /^\s*[-*]\s+/.test(lines[index])) {
        items.push(lines[index].replace(/^\s*[-*]\s+/, ""));
        index += 1;
      }
      html.push(`<ul>${items.map((item) => `<li>${inlineHtml(item, pageSlugValue)}</li>`).join("")}</ul>`);
      continue;
    }
    if (/^\s*\d+\.\s+/.test(line)) {
      const items = [];
      while (index < lines.length && /^\s*\d+\.\s+/.test(lines[index])) {
        items.push(lines[index].replace(/^\s*\d+\.\s+/, ""));
        index += 1;
      }
      html.push(`<ol>${items.map((item) => `<li>${inlineHtml(item, pageSlugValue)}</li>`).join("")}</ol>`);
      continue;
    }
    const paragraph = [];
    while (
      index < lines.length &&
      lines[index].trim() &&
      !isBlockStart(lines, index)
    ) {
      paragraph.push(lines[index]);
      index += 1;
    }
    html.push(`<p>${inlineHtml(paragraph.join(" "), pageSlugValue)}</p>`);
  }
  return html.join("\n");
}

function renderTable(lines, pageSlugValue) {
  const rows = lines
    .filter((line, index) => index !== 1)
    .map((line) =>
      line
        .trim()
        .replace(/^\|/, "")
        .replace(/\|$/, "")
        .split("|")
        .map((cell) => cell.trim()),
    );
  const [header = [], ...body] = rows;
  const head = header
    .map((cell) => `<th>${inlineHtml(cell, pageSlugValue)}</th>`)
    .join("");
  const rowsHtml = body
    .map(
      (row) =>
        `<tr>${row
          .map((cell) => `<td>${inlineHtml(cell, pageSlugValue)}</td>`)
          .join("")}</tr>`,
    )
    .join("");
  return `<table><thead><tr>${head}</tr></thead><tbody>${rowsHtml}</tbody></table>`;
}

function inlineHtml(value, pageSlugValue) {
  return escapeHtml(value)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\[([^\]]+)]\(([^)]+)\)/g, '<a href="$2">$1</a>')
    .replace(
      /\[\[(S\d+)]]/g,
      (_, citationId) =>
        `<a class="citation" href="#${escapeAttr(sourceId(pageSlugValue, citationId))}">[${citationId}]</a>`,
    );
}

function isTableStart(lines, index) {
  return (
    lines[index]?.includes("|") &&
    /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(
      lines[index + 1] || "",
    )
  );
}

function isBlockStart(lines, index) {
  const line = lines[index] || "";
  return (
    /^```/.test(line.trim()) ||
    /^(#{1,6})\s+/.test(line) ||
    isTableStart(lines, index) ||
    /^\s*[-*]\s+/.test(line) ||
    /^\s*\d+\.\s+/.test(line)
  );
}

function pageSlug(page) {
  return slugify(stringValue(page.slug) || pageTitle(page));
}

function pageTitle(page) {
  return stringValue(page.title) || stringValue(page.slug) || "Untitled";
}

function sourceId(slug, citationId) {
  return `source-${slugify(slug)}-${slugify(citationId)}`;
}

function slugify(value) {
  return String(value || "item")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 80) || "item";
}

function stripInlineMarkdown(value) {
  return String(value)
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/\[([^\]]+)]\(([^)]+)\)/g, "$1")
    .replace(/\[\[(S\d+)]]/g, "$1");
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function escapeAttr(value) {
  return escapeHtml(value);
}

function parseArgs(args) {
  const positional = [];
  const options = {};
  for (let index = 0; index < args.length; index += 1) {
    const arg = args[index];
    if (!arg.startsWith("--")) {
      positional.push(arg);
      continue;
    }
    const eq = arg.indexOf("=");
    if (eq > 2) {
      options[arg.slice(2, eq)] = arg.slice(eq + 1);
      continue;
    }
    const key = arg.slice(2);
    if (key === "help") {
      options.help = true;
      continue;
    }
    const next = args[index + 1];
    if (next && !next.startsWith("--")) {
      options[key] = next;
      index += 1;
    } else {
      options[key] = true;
    }
  }
  return { positional, options };
}

function printHelp() {
  process.stdout.write(`Usage: export-html.mjs <repo> [options]

Options:
  --language <code>       Wiki language. Default: en
  --output <path>         HTML output path. Default: codewiki-wiki.html
  --title <text>          Override document title.
  --codewiki-bin <path>   CodeWiki executable. Default: codewiki
`);
}

function arrayValue(value) {
  return Array.isArray(value) ? value : [];
}

function stringValue(value) {
  return typeof value === "string" && value.length ? value : null;
}

function numberValue(value) {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function stringOption(value, fallback) {
  return typeof value === "string" && value.length ? value : fallback;
}
