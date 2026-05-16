type LinkRenderer = (label: string, href: string) => string;

export function renderMarkdownToHtml(markdown: string, renderLink: LinkRenderer): string {
  const lines = markdown.replace(/\r\n/g, "\n").split("\n");
  const output: string[] = [];
  let paragraph: string[] = [];
  let listType: "ul" | "ol" | null = null;
  let listItems: string[] = [];
  let blockquote: string[] = [];
  let codeFence: { language: string; lines: string[] } | null = null;

  const flushParagraph = () => {
    if (paragraph.length === 0) {
      return;
    }
    output.push(`<p>${renderInline(paragraph.join(" "), renderLink)}</p>`);
    paragraph = [];
  };
  const flushList = () => {
    if (!listType) {
      return;
    }
    output.push(`<${listType}>${listItems.join("")}</${listType}>`);
    listType = null;
    listItems = [];
  };
  const flushBlockquote = () => {
    if (blockquote.length === 0) {
      return;
    }
    output.push(`<blockquote>${renderMarkdownToHtml(blockquote.join("\n"), renderLink)}</blockquote>`);
    blockquote = [];
  };
  const flushOpenBlocks = () => {
    flushParagraph();
    flushList();
    flushBlockquote();
  };

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    const trimmed = line.trim();

    if (codeFence) {
      if (trimmed.startsWith("```")) {
        output.push(
          `<pre><code${codeFence.language ? ` class="language-${escapeHtml(codeFence.language)}"` : ""}>${escapeHtml(codeFence.lines.join("\n"))}</code></pre>`
        );
        codeFence = null;
      } else {
        codeFence.lines.push(line);
      }
      continue;
    }

    if (trimmed.startsWith("```")) {
      flushOpenBlocks();
      codeFence = {
        language: trimmed.slice(3).trim(),
        lines: []
      };
      continue;
    }

    if (!trimmed) {
      flushOpenBlocks();
      continue;
    }

    if (line.trimStart().startsWith(">")) {
      flushParagraph();
      flushList();
      blockquote.push(line.replace(/^\s*>\s?/, ""));
      continue;
    }
    flushBlockquote();

    const tableDivider = lines[index + 1];
    if (looksLikeTableHeader(line, tableDivider)) {
      flushParagraph();
      flushList();
      const tableLines = [line, tableDivider];
      let cursor = index + 2;
      while (cursor < lines.length && looksLikeTableRow(lines[cursor])) {
        tableLines.push(lines[cursor]);
        cursor += 1;
      }
      output.push(renderTable(tableLines, renderLink));
      index = cursor - 1;
      continue;
    }

    const heading = /^(#{1,6})\s+(.+)$/.exec(trimmed);
    if (heading) {
      flushParagraph();
      flushList();
      const level = heading[1].length;
      output.push(`<h${level}>${renderInline(heading[2], renderLink)}</h${level}>`);
      continue;
    }

    if (/^([-*_])(?:\s*\1){2,}\s*$/.test(trimmed)) {
      flushOpenBlocks();
      output.push("<hr>");
      continue;
    }

    const unorderedItem = /^\s*[-*+]\s+(.+)$/.exec(line);
    const orderedItem = /^\s*\d+\.\s+(.+)$/.exec(line);
    if (unorderedItem || orderedItem) {
      flushParagraph();
      const nextListType = unorderedItem ? "ul" : "ol";
      if (listType && listType !== nextListType) {
        flushList();
      }
      listType = nextListType;
      listItems.push(`<li>${renderInline((unorderedItem ?? orderedItem)?.[1] ?? "", renderLink)}</li>`);
      continue;
    }

    flushList();
    paragraph.push(trimmed);
  }

  if (codeFence) {
    output.push(
      `<pre><code${codeFence.language ? ` class="language-${escapeHtml(codeFence.language)}"` : ""}>${escapeHtml(codeFence.lines.join("\n"))}</code></pre>`
    );
  }
  flushOpenBlocks();
  return output.join("\n");
}

export function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function renderInline(markdown: string, renderLink: LinkRenderer): string {
  let html = escapeHtml(markdown);
  html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
  html = html.replace(/(?<!!)\[([^\]]+)]\(([^)]+)\)/g, (_match, label: string, href: string) =>
    renderLink(label, decodeHtmlEntities(href))
  );
  html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/__([^_]+)__/g, "<strong>$1</strong>");
  html = html.replace(/~~([^~]+)~~/g, "<del>$1</del>");
  html = html.replace(/(^|[^*])\*([^*]+)\*/g, "$1<em>$2</em>");
  html = html.replace(/(^|[^_])_([^_]+)_/g, "$1<em>$2</em>");
  return html;
}

function looksLikeTableHeader(line: string, divider: string | undefined): boolean {
  return looksLikeTableRow(line) && Boolean(divider && /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(divider));
}

function looksLikeTableRow(line: string): boolean {
  return line.includes("|") && line.trim().length > 0;
}

function renderTable(lines: string[], renderLink: LinkRenderer): string {
  const rows = lines.map(splitTableRow);
  const headerCells = rows[0] ?? [];
  const bodyRows = rows.slice(2);
  const header = `<thead><tr>${headerCells.map((cell) => `<th>${renderInline(cell, renderLink)}</th>`).join("")}</tr></thead>`;
  const body = `<tbody>${bodyRows
    .map((cells) => `<tr>${cells.map((cell) => `<td>${renderInline(cell, renderLink)}</td>`).join("")}</tr>`)
    .join("")}</tbody>`;
  return `<table>${header}${body}</table>`;
}

function splitTableRow(line: string): string[] {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());
}

function decodeHtmlEntities(value: string): string {
  return value
    .replaceAll("&amp;", "&")
    .replaceAll("&lt;", "<")
    .replaceAll("&gt;", ">")
    .replaceAll("&quot;", '"')
    .replaceAll("&#39;", "'");
}
