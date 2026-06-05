import { randomUUID } from "node:crypto";
import type { CodeWikiStoreApi } from "../db/types.js";
import { notFoundError } from "../errors.js";
import {
  LlmCallError,
  type CachedLlmCompletion,
  type LlmOperation,
} from "../llm/cache.js";
import type {
  CodeChunk,
  CodeGraphNode,
  DocPage,
  JsonObject,
  RepoDescriptor,
} from "../types.js";
import type { WikiPageResult } from "./payloads.js";

export type WikiPageRequest = {
  repoId: string;
  slug: string;
  languageCode: string;
  title: string;
  path: string | null;
  parentSlug: string | null;
  childPages: DocPage[];
};

type WikiPageLlm = {
  isConfigured(taskType: string): boolean;
  complete(
    repoId: string,
    operation: LlmOperation,
  ): Promise<CachedLlmCompletion>;
};

type WikiPageContext = {
  repo: RepoDescriptor;
  request: WikiPageRequest;
  matchingNodes: CodeGraphNode[];
  matchingChunks: CodeChunk[];
  sourceRefs: JsonObject[];
  symbols: CodeGraphNode[];
};

export class WikiPageGenerator {
  constructor(
    private readonly store: CodeWikiStoreApi,
    private readonly llm?: WikiPageLlm,
  ) {}

  async generate(request: WikiPageRequest): Promise<DocPage> {
    const context = await this.pageContext(request);
    return this.savePage(
      context,
      localPageMarkdown(
        request.title,
        context.matchingNodes,
        context.matchingChunks,
        context.symbols,
        request.childPages,
      ),
    );
  }

  async generateWithLlmFallback(
    request: WikiPageRequest,
  ): Promise<WikiPageResult> {
    const context = await this.pageContext(request);
    const localPage = await this.savePage(
      context,
      localPageMarkdown(
        request.title,
        context.matchingNodes,
        context.matchingChunks,
        context.symbols,
        request.childPages,
      ),
    );
    if (
      !this.llm?.isConfigured("page") ||
      (!context.matchingChunks.length && !request.childPages.length)
    ) {
      return { page: localPage, validation_errors: [] };
    }

    try {
      const completion = await this.llm.complete(request.repoId, {
        taskType: "page",
        cacheKey: `wiki-page:${request.languageCode}:${request.slug}`,
        modelAlias: "page",
        promptVersion: "ts-wiki-page-v1",
        inputPayload: llmInputPayload(context),
        messages: wikiPageMessages(context),
      });
      const markdown = completion.result.content.trim();
      if (!markdown) {
        return {
          page: localPage,
          validation_errors: ["LLM returned an empty wiki page."],
          llm: {
            status: "fallback",
            error: "LLM returned an empty wiki page.",
            run_id: completion.run.id,
          },
        };
      }
      return {
        page: await this.savePage(context, markdown),
        validation_errors: [],
        llm: llmMetadata("success", completion),
      };
    } catch (error) {
      return {
        page: localPage,
        validation_errors: [],
        llm: {
          status: "fallback",
          error: error instanceof Error ? error.message : String(error),
          run_id: error instanceof LlmCallError ? error.runId : null,
        },
      };
    }
  }

  private async pageContext(
    request: WikiPageRequest,
  ): Promise<WikiPageContext> {
    const repo = await this.store.getRepo(request.repoId);
    if (!repo) {
      throw notFoundError("Repository", request.repoId);
    }
    const graph = await this.store.getGraph(request.repoId);
    const chunks = await this.store.listCodeChunks(request.repoId);
    const matchingNodes = nodesForPath(graph.nodes, request.path);
    const matchingChunks = chunksForNodes(chunks, matchingNodes).slice(0, 6);
    const sourceRefs = sourceRefsForChunks(matchingChunks);
    const symbols = matchingNodes
      .filter((node) => node.type !== "file" && node.type !== "config")
      .slice(0, 20);
    return {
      repo,
      request,
      matchingNodes,
      matchingChunks,
      sourceRefs,
      symbols,
    };
  }

  private async savePage(
    context: WikiPageContext,
    markdown: string,
  ): Promise<DocPage> {
    return this.store.upsertDocPage({
      id: randomUUID(),
      repo_id: context.request.repoId,
      language_code: context.request.languageCode,
      slug: context.request.slug,
      title: context.request.title,
      parent_slug: context.request.parentSlug,
      markdown,
      source_refs: context.sourceRefs,
      graph_refs: context.symbols.map((node) => node.id),
      status: "generated",
      updated_at: new Date().toISOString(),
    });
  }
}

function nodesForPath(
  nodes: CodeGraphNode[],
  path: string | null,
): CodeGraphNode[] {
  return nodes.filter((node) => {
    if (!path || path === "root") {
      return !node.file_path.includes("/");
    }
    return node.file_path === path || node.file_path.startsWith(`${path}/`);
  });
}

function chunksForNodes(
  chunks: CodeChunk[],
  nodes: CodeGraphNode[],
): CodeChunk[] {
  const nodeFilePaths = new Set(nodes.map((node) => node.file_path));
  return chunks.filter((chunk) => nodeFilePaths.has(chunk.file_path));
}

function sourceRefsForChunks(chunks: CodeChunk[]): JsonObject[] {
  return chunks.map((chunk, index) => ({
    citation_id: `S${index + 1}`,
    file_path: chunk.file_path,
    start_line: chunk.start_line,
    end_line: chunk.end_line,
    source_url: null,
  }));
}

function localPageMarkdown(
  title: string,
  matchingNodes: CodeGraphNode[],
  matchingChunks: CodeChunk[],
  symbols: CodeGraphNode[],
  childPages: DocPage[],
): string {
  return [
    `# ${title}`,
    "",
    "This page was generated by the TypeScript CodeWiki backend from indexed source files.",
    "",
    ...(childPages.length
      ? [
          "## Child Pages",
          "",
          ...childPages.map(
            (page) => `- [${page.title}](#${page.slug}) (${page.status})`,
          ),
          "",
        ]
      : []),
    "",
    "## Key Files",
    "",
    ...[...new Set(matchingNodes.map((node) => node.file_path))]
      .slice(0, 20)
      .map((filePath) => `- \`${filePath}\``),
    "",
    "## Symbols",
    "",
    ...(symbols.length
      ? symbols.map(
          (node) =>
            `- \`${node.name}\` (${node.type}) in \`${node.file_path}\``,
        )
      : [
          "- No symbols were detected yet. Run analysis after adding source files.",
        ]),
    "",
    "## Source Notes",
    "",
    ...(matchingChunks.length
      ? matchingChunks.map(
          (chunk, index) =>
            `- [S${index + 1}] \`${chunk.file_path}:${chunk.start_line}\``,
        )
      : ["- No source chunks are available yet."]),
  ].join("\n");
}

function wikiPageMessages(context: WikiPageContext): LlmOperation["messages"] {
  return [
    {
      role: "system",
      content: [
        "You generate concise source-grounded wiki pages for a code repository.",
        "Use only the provided CodeWiki context.",
        "Keep Markdown headings and cite source snippets with bracketed citation ids such as [S1].",
        "If context is thin, explain what is known and what is missing.",
      ].join(" "),
    },
    {
      role: "user",
      content: `Wiki page request:\n${JSON.stringify(llmInputPayload(context))}`,
    },
  ];
}

function llmInputPayload(context: WikiPageContext): JsonObject {
  return {
    repo_name: context.repo.name,
    language_code: context.request.languageCode,
    slug: context.request.slug,
    title: context.request.title,
    parent_slug: context.request.parentSlug,
    path: context.request.path,
    child_pages: context.request.childPages.map((page) => ({
      slug: page.slug,
      title: page.title,
      status: page.status,
      source_refs: page.source_refs.slice(0, 6),
      graph_refs: page.graph_refs.slice(0, 12),
      overview_markdown: firstContentSection(page.markdown).slice(0, 1600),
    })),
    files: [...new Set(context.matchingNodes.map((node) => node.file_path))]
      .slice(0, 20)
      .map((filePath) => ({ file_path: filePath })),
    symbols: context.symbols.map((node) => ({
      id: node.id,
      name: node.name,
      type: node.type,
      file_path: node.file_path,
      start_line: node.start_line,
      end_line: node.end_line,
      language: node.language,
    })),
    sources: context.matchingChunks.map((chunk, index) => ({
      citation_id: `S${index + 1}`,
      file_path: chunk.file_path,
      start_line: chunk.start_line,
      end_line: chunk.end_line,
      content: chunk.content,
    })),
  };
}

function firstContentSection(markdown: string): string {
  const lines = markdown.split(/\r?\n/);
  const section: string[] = [];
  let inSection = false;
  for (const line of lines) {
    if (line.startsWith("## ")) {
      if (inSection && section.length) {
        break;
      }
      inSection = true;
    }
    if (inSection) {
      section.push(line);
    }
  }
  return (section.length ? section.join("\n") : markdown).trim();
}

function llmMetadata(
  status: "success",
  completion: CachedLlmCompletion,
): JsonObject {
  return {
    status,
    cache_hit: completion.cacheHit,
    run_id: completion.run.id,
    model: completion.result.model,
    provider: completion.result.provider,
  };
}
