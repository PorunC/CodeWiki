import type { SourceRef } from "../../api/types";
import type { RelevantSourceFile } from "../types";

const SOURCES_HEADING_RE = /^#{2,6}\s+(?:Sources|来源|资料来源|引用来源|源文件来源)\s*$/i;
const RELEVANT_SOURCE_FILES_HEADING_RE =
  /^##\s+(?:Relevant source files|相关源文件|相关源码文件|相关源代码文件|关联源文件)\s*$/i;

export function stripMarkdownSourcesSection(markdown: string): string {
  const lines = markdown.split(/\r?\n/);
  let inFence = false;
  let sourcesHeadingIndex = -1;

  lines.forEach((line, index) => {
    if (line.trimStart().startsWith("```")) {
      inFence = !inFence;
      return;
    }
    if (!inFence && SOURCES_HEADING_RE.test(line.trim())) {
      sourcesHeadingIndex = index;
    }
  });

  if (sourcesHeadingIndex < 0) {
    return markdown;
  }

  return lines.slice(0, sourcesHeadingIndex).join("\n").trimEnd();
}

export function extractRelevantSourceFilesSection(markdown: string): {
  titleMarkdown: string;
  bodyMarkdown: string;
  relevantFiles: RelevantSourceFile[];
} {
  const lines = markdown.split(/\r?\n/);
  const relevantStart = lines.findIndex((line) =>
    RELEVANT_SOURCE_FILES_HEADING_RE.test(line.trim())
  );
  const titleMarkdown = lines[0]?.startsWith("# ") ? lines[0] : "";

  if (relevantStart < 0) {
    return {
      titleMarkdown,
      bodyMarkdown: titleMarkdown ? lines.slice(1).join("\n").trimStart() : markdown,
      relevantFiles: []
    };
  }

  let relevantEnd = lines.length;
  for (let index = relevantStart + 1; index < lines.length; index += 1) {
    if (/^#{1,6}\s+/.test(lines[index].trim())) {
      relevantEnd = index;
      break;
    }
  }

  const relevantFiles = lines
    .slice(relevantStart + 1, relevantEnd)
    .map(parseRelevantSourceFile)
    .filter((file): file is RelevantSourceFile => file !== null);
  const withoutRelevant = [...lines.slice(0, relevantStart), ...lines.slice(relevantEnd)];
  return {
    titleMarkdown,
    bodyMarkdown: titleMarkdown ? withoutRelevant.slice(1).join("\n").trimStart() : withoutRelevant.join("\n").trim(),
    relevantFiles
  };
}

export function parseRelevantSourceFile(line: string): RelevantSourceFile | null {
  const trimmed = line.trim();
  if (!trimmed.startsWith("- ")) {
    return null;
  }
  const linkMatch = /^-\s+\[([^\]]+)]\(([^)]+)\)\s*$/.exec(trimmed);
  if (linkMatch) {
    return {
      label: linkMatch[1],
      href: linkMatch[2]
    };
  }
  const label = trimmed.replace(/^-\s+/, "").trim();
  return label ? { label, href: "source-link" } : null;
}

export function formatSourceRef(source: SourceRef): string {
  return `${source.file_path}:L${source.start_line}-L${source.end_line}`;
}
