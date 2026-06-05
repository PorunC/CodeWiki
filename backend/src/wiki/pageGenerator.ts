import { randomUUID } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import { isAbsolute, relative, resolve } from "node:path";
import type { CodeWikiStoreApi } from "../db/types.js";
import { notFoundError } from "../errors.js";
import { buildRetrievalTrace } from "../graphrag/retrieval.js";
import {
  LlmCallError,
  type CachedLlmCompletion,
  type LlmOperation,
} from "../llm/cache.js";
import {
  sourceUrlBaseForRepo,
  sourceUrlForRange,
} from "../services/sourceUrls.js";
import type {
  CodeChunk,
  CodeGraphNode,
  DocCatalog,
  DocPage,
  JsonObject,
  RepoDescriptor,
  RetrievalTrace,
} from "../types.js";
import {
  catalogItemChildren,
  catalogItemsFromStructure,
  catalogItemTitle,
  catalogSlug,
  type CatalogItem,
} from "./catalog.js";
import type { WikiPageResult } from "./payloads.js";

export type WikiPageRequest = {
  repoId: string;
  slug: string;
  languageCode: string;
  title: string;
  path: string | null;
  topic: string;
  sourceHints: string[];
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
  sourceRefs: SourceRef[];
  symbols: CodeGraphNode[];
  retrievalTrace: RetrievalTrace;
  catalog: DocCatalog | null;
};

type NormalizedPage = {
  title: string;
  markdown: string;
  sourceRefs: SourceRef[];
  diagrams: MermaidDiagram[];
  validationErrors: string[];
};

type SourceRef = JsonObject & {
  citation_id?: string;
  file_path: string;
  start_line: number;
  end_line: number;
  chunk_id?: string;
  source_url?: string;
  read_via?: string;
};

type MermaidDiagram = {
  slot: string;
  kind: "component" | "symbol_flow" | "sequence";
  title: string;
  headingHint: string;
  lines: string[];
};

const PAGE_GENERATION_ATTEMPTS = 2;
const PAGE_RETRIEVAL_MAX_HOPS = 3;
const PAGE_SOURCE_LIMIT = 14;
const PAGE_SYMBOL_LIMIT = 40;
const PAGE_READFILE_LIMIT = 14;
const PAGE_READFILE_MAX_CHARS = 32_000;
const PAGE_READFILE_SINGLE_MAX_CHARS = 8_000;
const PAGE_PROMPT_VERSION = "ts-wiki-page-deepwiki-v2";
const CITATION_MARKER_RE = /\[\[(S\d+)]]/g;
const CITATION_LIKE_MARKER_RE = /\[\[(S[^[\]]*)]]/g;
const MERMAID_FENCE_RE = /```mermaid[\s\S]*?```/gi;
const DIAGRAM_SLOT_RE = /^\s*\[\[DIAGRAM:([a-zA-Z0-9_-]+)]]\s*$/gm;
const FENCED_DIAGRAM_SLOT_RE =
  /^[ \t]*`{3,}[ \t]*\n[ \t]*\[\[DIAGRAM:([a-zA-Z0-9_-]+)]][ \t]*\n[ \t]*`{3,}[ \t]*$/gm;
const INLINE_SOURCES_LINE_RE = /^(?:>\s*)?(?:\*\*)?sources?(?:\*\*)?:\s+\S/i;
const BOLD_INLINE_SOURCES_LINE_RE = /^(?:>\s*)?\*\*sources?:\*\*\s+\S/i;

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
    if (
      !this.llm?.isConfigured("page") ||
      (!context.matchingChunks.length && !request.childPages.length)
    ) {
      return {
        page: await this.savePage(
          context,
          localPageMarkdown(
            request.title,
            context.matchingNodes,
            context.matchingChunks,
            context.symbols,
            request.childPages,
          ),
        ),
        validation_errors: [],
      };
    }

    try {
      let attemptPayload = llmInputPayload(context);
      let validationErrors: string[] = [];
      let completion: CachedLlmCompletion | null = null;
      let lastNormalized: NormalizedPage | null = null;
      for (let attempt = 0; attempt < PAGE_GENERATION_ATTEMPTS; attempt += 1) {
        completion = await this.llm.complete(request.repoId, {
          taskType: "page",
          cacheKey: `wiki-page:${request.languageCode}:${request.slug}:${context.retrievalTrace.trace_id}:attempt:${attempt + 1}`,
          modelAlias: "page",
          promptVersion: PAGE_PROMPT_VERSION,
          inputPayload: attemptPayload,
          messages: wikiPageMessages(context, attemptPayload, validationErrors),
          completion: { responseFormat: "json_object" },
        });
        const normalized = normalizePageCompletion(
          completion.result.content,
          context,
        );
        lastNormalized = normalized;
        validationErrors = normalized.validationErrors;
        if (!validationErrors.length) {
          return {
            page: await this.savePage(context, normalized.markdown, {
              title: normalized.title,
              sourceRefs: normalized.sourceRefs,
            }),
            validation_errors: [],
            llm: llmMetadata("success", completion),
          };
        }

        await this.store.updateLlmRunStatus(completion.run.id, {
          status: "error",
          error: validationErrors.join("; "),
        });
        attemptPayload = pageRepairPayload(
          llmInputPayload(context),
          completion.result.content,
          validationErrors,
        );
      }

      return {
        page: await this.savePage(
          context,
          draftMarkdown(context.request.title, validationErrors),
          {
            title: lastNormalized?.title ?? context.request.title,
            sourceRefs: lastNormalized?.sourceRefs ?? [],
            status: "draft",
          },
        ),
        validation_errors: validationErrors,
        llm: {
          status: "fallback",
          error:
            validationErrors.join("; ") ||
            "LLM did not return a valid wiki page.",
          run_id: completion?.run.id ?? null,
        },
      };
    } catch (error) {
      const validationErrors = [
        `LLM provider call failed: ${error instanceof Error ? error.message : String(error)}`,
      ];
      return {
        page: await this.savePage(
          context,
          draftMarkdown(context.request.title, validationErrors),
          {
            sourceRefs: [],
            status: "draft",
          },
        ),
        validation_errors: validationErrors,
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
    const catalog = await this.store.getLatestDocCatalog(
      request.repoId,
      request.languageCode,
    );
    const retrievalTrace = await this.store.saveRetrievalTrace(
      await buildRetrievalTrace(
        this.store,
        request.repoId,
        retrievalQuery(request),
        {
          maxHops: PAGE_RETRIEVAL_MAX_HOPS,
          limit: PAGE_SOURCE_LIMIT,
        },
      ),
    );
    const pathNodes = nodesForPath(graph.nodes, request.path);
    const traceNodeIds = nodeIdsFromTrace(retrievalTrace);
    const traceNodes = graph.nodes.filter((node) => traceNodeIds.has(node.id));
    const matchingNodes = uniqueNodes([...traceNodes, ...pathNodes]);
    const matchingChunks = uniqueChunks([
      ...retrievalTrace.chunks,
      ...chunksForSourceHints(chunks, request.sourceHints),
      ...chunksForNodes(chunks, pathNodes),
    ]).slice(0, PAGE_SOURCE_LIMIT);
    const sourceRefs = sourceRefsForChunks(matchingChunks, repo);
    const symbols = matchingNodes
      .filter((node) => node.type !== "file" && node.type !== "config")
      .slice(0, PAGE_SYMBOL_LIMIT);
    return {
      repo,
      request,
      matchingNodes,
      matchingChunks,
      sourceRefs,
      symbols,
      retrievalTrace,
      catalog,
    };
  }

  private async savePage(
    context: WikiPageContext,
    markdown: string,
    options: {
      title?: string | undefined;
      sourceRefs?: JsonObject[] | undefined;
      status?: string | undefined;
    } = {},
  ): Promise<DocPage> {
    return this.store.upsertDocPage({
      id: randomUUID(),
      repo_id: context.request.repoId,
      language_code: context.request.languageCode,
      slug: context.request.slug,
      title: options.title ?? context.request.title,
      parent_slug: context.request.parentSlug,
      markdown,
      source_refs: options.sourceRefs ?? context.sourceRefs,
      graph_refs: graphRefsForContext(context),
      status: options.status ?? "generated",
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

function sourceRefsForChunks(
  chunks: CodeChunk[],
  repo: RepoDescriptor,
): SourceRef[] {
  const sourceUrlBase = sourceUrlBaseForRepo(repo);
  return chunks.map((chunk, index) => ({
    citation_id: `S${index + 1}`,
    file_path: chunk.file_path,
    start_line: chunk.start_line,
    end_line: chunk.end_line,
    chunk_id: chunk.id,
    ...(sourceUrlBase
      ? {
          source_url: sourceUrlForRange(
            sourceUrlBase,
            chunk.file_path,
            chunk.start_line,
            chunk.end_line,
          ),
        }
      : {}),
  }));
}

function retrievalQuery(request: WikiPageRequest): string {
  return uniqueStrings([
    request.topic,
    request.title,
    request.path ?? "",
    ...request.sourceHints.slice(0, 8),
  ])
    .filter(Boolean)
    .join("\n");
}

function nodeIdsFromTrace(trace: RetrievalTrace): Set<string> {
  const ids = new Set<string>();
  for (const node of [...trace.seed_nodes, ...trace.expanded_nodes]) {
    const id = node.id;
    if (typeof id === "string" && id) {
      ids.add(id);
    }
  }
  return ids;
}

function uniqueNodes(nodes: CodeGraphNode[]): CodeGraphNode[] {
  const byId = new Map<string, CodeGraphNode>();
  for (const node of nodes) {
    byId.set(node.id, node);
  }
  return [...byId.values()];
}

function uniqueChunks(chunks: CodeChunk[]): CodeChunk[] {
  const byId = new Map<string, CodeChunk>();
  for (const chunk of chunks) {
    byId.set(chunk.id, chunk);
  }
  return [...byId.values()];
}

function chunksForSourceHints(
  chunks: CodeChunk[],
  sourceHints: string[],
): CodeChunk[] {
  const hints = sourceHints.map(normalizedPath).filter(Boolean);
  if (!hints.length) {
    return [];
  }
  return chunks.filter((chunk) =>
    hints.some((hint) => pathMatchesHint(chunk.file_path, hint)),
  );
}

function pathMatchesHint(filePath: string, hint: string): boolean {
  const normalized = normalizedPath(filePath);
  return normalized === hint || normalized.startsWith(`${hint}/`);
}

function normalizedPath(value: string): string {
  return value
    .replace(/\\/g, "/")
    .replace(/^\/+|\/+$/g, "")
    .trim();
}

function uniqueStrings(values: string[]): string[] {
  return [...new Set(values.map((value) => value.trim()).filter(Boolean))];
}

function graphRefsForContext(context: WikiPageContext): string[] {
  return uniqueStrings([
    ...context.symbols.map((node) => node.id),
    ...nodeIdsFromTrace(context.retrievalTrace),
  ]);
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

function stableCatalogContext(catalog: DocCatalog | null): JsonObject | null {
  if (!catalog) {
    return null;
  }
  return {
    title: catalog.title,
    items: catalogItemsFromStructure(catalog.structure).map(stableCatalogItem),
  };
}

function stableCatalogItem(item: CatalogItem): JsonObject {
  const payload: JsonObject = {
    title: catalogItemTitle(item),
    slug: catalogSlug(item),
  };
  const path = stringValue(item.path);
  const topic = stringValue(item.topic);
  if (path) {
    payload.path = path;
  }
  if (topic) {
    payload.topic = topic;
  }
  if (item.kind) {
    payload.kind = item.kind;
  }
  const children = catalogItemChildren(item).map(stableCatalogItem);
  if (children.length) {
    payload.children = children;
  }
  return payload;
}

function catalogContextForPage(context: WikiPageContext): JsonObject {
  const items = context.catalog
    ? catalogItemsFromStructure(context.catalog.structure)
    : [];
  const summaries = catalogItemSummaries(items);
  const current =
    summaries.find((item) => stringValue(item.slug) === context.request.slug) ??
    fallbackCatalogSummary(context.request);
  const parent = context.request.parentSlug
    ? (summaries.find(
        (item) => stringValue(item.slug) === context.request.parentSlug,
      ) ?? null)
    : null;
  return {
    current,
    parent,
    related_pages: relatedCatalogPages(
      summaries,
      context.request.slug,
      context.request.parentSlug,
    ),
    child_pages: context.request.childPages.map((page) => ({
      slug: page.slug,
      title: page.title,
      status: page.status,
    })),
    page_count: summaries.filter((item) => item.kind === "page").length,
  };
}

function fallbackCatalogSummary(request: WikiPageRequest): JsonObject {
  return {
    title: request.title,
    slug: request.slug,
    path: request.path ?? request.slug,
    kind: "page",
    parent_slug: request.parentSlug,
    depth: 0,
    source_hints: request.sourceHints.slice(0, 4),
  };
}

function catalogItemSummaries(
  items: CatalogItem[],
  parentSlug: string | null = null,
  depth = 0,
): JsonObject[] {
  const summaries: JsonObject[] = [];
  for (const item of items) {
    const slug = catalogSlug(item);
    const kind = item.kind ?? "page";
    summaries.push({
      title: catalogItemTitle(item),
      slug,
      path: stringValue(item.path) ?? slug,
      kind,
      topic: stringValue(item.topic) ?? catalogItemTitle(item),
      parent_slug: parentSlug,
      order: item.order ?? 0,
      depth,
      source_hints: Array.isArray(item.source_hints)
        ? item.source_hints.slice(0, 4)
        : [],
    });
    summaries.push(
      ...catalogItemSummaries(catalogItemChildren(item), slug, depth + 1),
    );
  }
  return summaries.slice(0, 48);
}

function relatedCatalogPages(
  summaries: JsonObject[],
  slug: string,
  parentSlug: string | null,
): JsonObject[] {
  return summaries
    .filter((item) => item.kind === "page" && stringValue(item.slug) !== slug)
    .sort(
      (left, right) =>
        (stringValue(left.parent_slug) === parentSlug ? 0 : 1) -
          (stringValue(right.parent_slug) === parentSlug ? 0 : 1) ||
        (numberValue(left.depth) ?? 0) - (numberValue(right.depth) ?? 0) ||
        (numberValue(left.order) ?? 0) - (numberValue(right.order) ?? 0) ||
        (stringValue(left.title) ?? "").localeCompare(
          stringValue(right.title) ?? "",
        ),
    )
    .slice(0, 12);
}

function wikiPageMessages(
  context: WikiPageContext,
  pagePayload: JsonObject,
  validationErrors: string[] = [],
): LlmOperation["messages"] {
  return [
    {
      role: "system",
      content: pageSystemPrompt(),
    },
    {
      role: "user",
      content: jsonMessage("Stable page generation contract", {
        instructions:
          "Return only one JSON object. Use [[S#]] markers only for refs you return in source_refs. Do not emit Mermaid; the server owns diagram and source rendering.",
        prompt_contract: promptContract(),
      }),
    },
    {
      role: "user",
      content: jsonMessage("Stable repository wiki context", {
        repository: {
          id: context.repo.id,
          name: context.repo.name,
          path: context.repo.path,
          source_type: context.repo.source_type,
          git_url: context.repo.git_url,
          commit_hash: context.repo.commit_hash,
        },
        language_code: context.request.languageCode,
        catalog: stableCatalogContext(context.catalog),
      }),
    },
    {
      role: "user",
      content: jsonMessage(
        "Page payload",
        validationErrors.length
          ? {
              ...pagePayload,
              validation_errors: validationErrors,
              repair_instructions:
                "Repair the previous response. Keep the title, include Purpose and Scope, choose source_refs only from allowed_source_refs, and cite only returned source refs.",
            }
          : pagePayload,
      ),
    },
  ];
}

function llmInputPayload(context: WikiPageContext): JsonObject {
  const evidenceInventory = evidenceInventoryPayload(context);
  const evidenceCounts = recordValue(evidenceInventory.counts);
  const availableEdgeTypes = stringArrayValue(evidenceInventory.edge_types);
  const availableNodeTypes = stringArrayValue(evidenceInventory.node_types);
  return {
    repo_name: context.repo.name,
    title: context.request.title,
    slug: context.request.slug,
    path: context.request.path,
    topic: context.request.topic,
    language_code: context.request.languageCode,
    source_hints: context.request.sourceHints,
    catalog_context: catalogContextForPage(context),
    parent_slug: context.request.parentSlug,
    parent_synthesis: {
      has_child_pages: context.request.childPages.length > 0,
      instructions:
        "When child_page_summaries is non-empty, synthesize this parent page primarily from child overviews. Use source_chunks and graph_facts to ground citations, fill gaps, and avoid unsupported claims.",
    },
    child_page_summaries: childPageSummaries(context.request.childPages),
    page_depth_profile: {
      kind: context.request.childPages.length
        ? "parent_synthesis"
        : "implementation_deep_dive",
      expected_detail_level: context.request.childPages.length
        ? "medium_high"
        : "high",
      evidence_counts: evidenceCounts,
      available_edge_types: availableEdgeTypes,
      available_node_types: availableNodeTypes,
    },
    diagram_slots: diagramSlotsPayload(mermaidDiagramsFromContext(context)),
    evidence_inventory: evidenceInventory,
    context_pack: context.retrievalTrace.context_pack,
    source_chunks: sourceChunkMetadata(context.matchingChunks),
    allowed_source_refs: context.sourceRefs,
    readfile_evidence: readFileEvidence(context),
    graph_facts: graphFactsPayload(context.retrievalTrace),
    files: [...new Set(context.matchingNodes.map((node) => node.file_path))]
      .slice(0, PAGE_SYMBOL_LIMIT)
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

function normalizePageCompletion(
  content: string,
  context: WikiPageContext,
): NormalizedPage {
  const validationErrors: string[] = [];
  const parsed = parseJsonObject(content, validationErrors);
  const fallbackTitle = context.request.title;
  if (!parsed) {
    return {
      title: fallbackTitle,
      markdown: "",
      sourceRefs: [],
      diagrams: [],
      validationErrors,
    };
  }

  const title = nonEmptyString(parsed.title) ?? fallbackTitle;
  let markdown = normalizeCitationLikeMarkers(
    stripMermaid(nonEmptyString(parsed.markdown) ?? ""),
  ).trim();
  const sourceValidation = validateSourceRefs(parsed.source_refs, context);
  let sourceRefs = sourceValidation.sourceRefs;
  sourceRefs = includeMarkdownCitationRefs(
    markdown,
    sourceRefs,
    context.sourceRefs,
  );
  sourceRefs = filterUnusedSourceRefs(markdown, sourceRefs);
  if (context.sourceRefs.length && !sourceRefs.length) {
    validationErrors.push(
      ...sourceValidation.errors,
      "At least one valid source_ref is required.",
    );
  } else {
    sourceRefs = mergeReadFileSourceRefs(
      sourceRefs,
      readSourceRefsForContext(context),
      sourceUrlBaseForRepo(context.repo),
    );
    markdown = stripUnknownCitationMarkers(markdown, sourceRefs);
  }
  const diagrams = mermaidDiagramsFromContext(context);
  validationErrors.push(...validatePageMarkdown(markdown, fallbackTitle));
  validationErrors.push(...validateCitationMarkers(markdown, sourceRefs));
  validationErrors.push(...validateDiagramPlaceholders(markdown, diagrams));

  return {
    title,
    markdown: validationErrors.length
      ? markdown
      : composePageMarkdown(
          replaceCitationMarkers(markdown, sourceRefs),
          diagrams,
          sourceRefs,
        ),
    sourceRefs,
    diagrams,
    validationErrors,
  };
}

function validateSourceRefs(
  rawRefs: unknown,
  context: WikiPageContext,
): { sourceRefs: SourceRef[]; errors: string[] } {
  if (!Array.isArray(rawRefs)) {
    return { sourceRefs: [], errors: ["source_refs must be an array."] };
  }
  const repoRoot = resolve(context.repo.path);
  const sourceUrlBase = sourceUrlBaseForRepo(context.repo);
  const allowedByCitation = sourceRefsByCitationId(context.sourceRefs);
  const sourceRefs: SourceRef[] = [];
  const errors: string[] = [];
  const seen = new Set<string>();
  rawRefs.forEach((rawRef, index) => {
    if (!isRecord(rawRef)) {
      errors.push(`source_refs[${index}] must be an object.`);
      return;
    }
    const citationId = nonEmptyString(rawRef.citation_id);
    const allowed = citationId ? allowedByCitation.get(citationId) : null;
    if (citationId && !allowed) {
      errors.push(
        `source_refs[${index}] uses unknown citation_id: ${citationId}.`,
      );
      return;
    }
    const filePath = allowed?.file_path ?? nonEmptyString(rawRef.file_path);
    const startLine = allowed?.start_line ?? numberValue(rawRef.start_line);
    const endLine = allowed?.end_line ?? numberValue(rawRef.end_line);
    if (!filePath || !startLine || !endLine) {
      errors.push(
        `source_refs[${index}] must include file_path, start_line, end_line.`,
      );
      return;
    }
    if (startLine < 1 || endLine < startLine) {
      errors.push(`source_refs[${index}] has invalid line range.`);
      return;
    }
    const absolutePath = resolve(repoRoot, filePath);
    if (!isPathInside(repoRoot, absolutePath) || !existsSync(absolutePath)) {
      errors.push(
        `source_refs[${index}] file does not exist in repo: ${filePath}.`,
      );
      return;
    }
    let lines: string[];
    try {
      lines = readFileSync(absolutePath, "utf8").split(/\r?\n/);
    } catch {
      errors.push(`source_refs[${index}] file could not be read: ${filePath}.`);
      return;
    }
    if (endLine > lines.length) {
      errors.push(
        `source_refs[${index}] line range exceeds file length: ${filePath}.`,
      );
      return;
    }
    const matchingChunk = matchingSourceChunk(
      context.matchingChunks,
      filePath,
      startLine,
      endLine,
      lines,
    );
    if (!matchingChunk) {
      errors.push(
        `source_refs[${index}] is not covered by the retrieved source_chunks: ${filePath}:${startLine}-${endLine}.`,
      );
      return;
    }
    const key = `${filePath}:${startLine}:${endLine}`;
    if (seen.has(key)) {
      return;
    }
    seen.add(key);
    const resolvedCitationId =
      citationId ??
      citationIdForRange(context.sourceRefs, filePath, startLine, endLine);
    const ref: SourceRef = {
      file_path: filePath,
      start_line: startLine,
      end_line: endLine,
      chunk_id: matchingChunk.id,
    };
    if (resolvedCitationId) {
      ref.citation_id = resolvedCitationId;
    }
    if (sourceUrlBase) {
      ref.source_url = sourceUrlForRange(
        sourceUrlBase,
        filePath,
        startLine,
        endLine,
      );
    }
    sourceRefs.push(ref);
  });
  return { sourceRefs, errors };
}

function includeMarkdownCitationRefs(
  markdown: string,
  sourceRefs: SourceRef[],
  allowedSourceRefs: SourceRef[],
): SourceRef[] {
  const byCitationId = sourceRefsByCitationId(sourceRefs);
  const allowedByCitationId = sourceRefsByCitationId(allowedSourceRefs);
  for (const citationId of citationMarkers(markdown)) {
    if (!byCitationId.has(citationId)) {
      const allowed = allowedByCitationId.get(citationId);
      if (allowed) {
        byCitationId.set(citationId, allowed);
      }
    }
  }
  return [...byCitationId.values()];
}

function filterUnusedSourceRefs(
  markdown: string,
  sourceRefs: SourceRef[],
): SourceRef[] {
  const markers = new Set(citationMarkers(markdown));
  if (!markers.size) {
    return sourceRefs;
  }
  return sourceRefs.filter((ref) => {
    const citationId = stringValue(ref.citation_id);
    return !citationId || markers.has(citationId);
  });
}

function validateCitationMarkers(
  markdown: string,
  sourceRefs: SourceRef[],
): string[] {
  const sourceRefMarkers = new Set(
    sourceRefs
      .map((ref) => stringValue(ref.citation_id))
      .filter((value): value is string => Boolean(value)),
  );
  const unknown = citationMarkers(markdown).filter(
    (citationId) => !sourceRefMarkers.has(citationId),
  );
  return unknown.length
    ? [
        `markdown contains citation markers not present in source_refs: ${uniqueStrings(unknown).join(", ")}.`,
      ]
    : [];
}

function validatePageMarkdown(
  markdown: string,
  expectedTitle: string,
): string[] {
  const errors: string[] = [];
  const lines = markdown.trim().split(/\r?\n/);
  if (!lines[0]?.startsWith("# ")) {
    errors.push("markdown must start with an H1 title.");
  }
  if (expectedTitle && !lines.slice(0, 3).includes(`# ${expectedTitle}`)) {
    errors.push(`markdown H1 must match page title: ${expectedTitle}.`);
  }
  if (!markdown.includes("## Purpose and Scope")) {
    errors.push(
      "markdown must include required heading: ## Purpose and Scope.",
    );
  }
  return errors;
}

function composePageMarkdown(
  markdown: string,
  diagrams: MermaidDiagram[],
  sourceRefs: SourceRef[],
): string {
  let body = stripInlineSourcesLines(stripSourcesSection(markdown));
  body = insertRelevantSourceFiles(body, sourceRefs);
  body = placeDiagrams(body, diagrams);
  return [body, sourcesMarkdown(sourceRefs)]
    .filter((section) => section.trim())
    .join("\n\n");
}

function insertRelevantSourceFiles(
  markdown: string,
  sourceRefs: SourceRef[],
): string {
  if (!sourceRefs.length || /^## Relevant source files$/im.test(markdown)) {
    return markdown.trim();
  }
  const lines = markdown.trim().split(/\r?\n/);
  const files = uniqueStrings(
    sourceRefs.map((ref) => stringValue(ref.file_path) ?? ""),
  );
  const relevant = [
    "## Relevant source files",
    ...files.map((filePath) => {
      const ref = sourceRefs.find(
        (sourceRef) => sourceRef.file_path === filePath,
      );
      return `- [${filePath}](${sourceFileHref(ref)})`;
    }),
  ].join("\n");
  if (lines[0]?.startsWith("# ")) {
    return [lines[0], relevant, lines.slice(1).join("\n").trim()]
      .filter(Boolean)
      .join("\n\n");
  }
  return [relevant, markdown.trim()].join("\n\n");
}

function sourcesMarkdown(sourceRefs: SourceRef[]): string {
  if (!sourceRefs.length) {
    return "";
  }
  const lines = ["## Sources"];
  for (const [filePath, refs] of groupedSourceRefs(sourceRefs)) {
    const fileHref = sourceFileHref(refs[0]);
    lines.push(
      `- ${fileHref === "source-link" ? filePath : `[${filePath}](${fileHref})`}`,
    );
    for (const ref of refs) {
      const citationId = ref.citation_id ? `${ref.citation_id} ` : "";
      lines.push(
        `  - ${citationId}[L${ref.start_line}-L${ref.end_line}](${sourceRefHref(ref)})`,
      );
    }
  }
  return lines.join("\n");
}

function stripSourcesSection(markdown: string): string {
  const lines = markdown.split(/\r?\n/);
  const index = lines.findIndex((line) => /^#{2,6}\s+Sources\s*$/i.test(line));
  return (index >= 0 ? lines.slice(0, index) : lines).join("\n").trim();
}

function replaceCitationMarkers(
  markdown: string,
  sourceRefs: SourceRef[],
): string {
  const byCitationId = sourceRefsByCitationId(sourceRefs);
  const normalizedMarkdown = separateAdjacentCitationMarkers(
    stripRedundantSourceLabels(unwrapCodeWrappedCitationMarkers(markdown)),
  );
  return normalizedMarkdown.replace(
    CITATION_MARKER_RE,
    (marker, citationId: string) => {
      const ref = byCitationId.get(citationId);
      if (!ref) {
        return marker;
      }
      return `[${citationId}](${sourceRefHref(ref)} "${sourceRefLabel(ref)}")`;
    },
  );
}

function sourceRefLabel(ref: SourceRef): string {
  return `${ref.file_path}:L${ref.start_line}-L${ref.end_line}`.replace(
    /"/g,
    "'",
  );
}

function sourceRefsByCitationId(
  sourceRefs: SourceRef[],
): Map<string, SourceRef> {
  return new Map(
    sourceRefs
      .map((ref) => [stringValue(ref.citation_id), ref] as const)
      .filter((entry): entry is readonly [string, SourceRef] =>
        Boolean(entry[0]),
      ),
  );
}

function citationIdForRange(
  sourceRefs: SourceRef[],
  filePath: string,
  startLine: number,
  endLine: number,
): string | null {
  return (
    sourceRefs.find(
      (ref) =>
        ref.file_path === filePath &&
        ref.start_line === startLine &&
        ref.end_line === endLine &&
        Boolean(ref.citation_id),
    )?.citation_id ?? null
  );
}

function matchingSourceChunk(
  chunks: CodeChunk[],
  filePath: string,
  startLine: number,
  endLine: number,
  lines: string[],
): CodeChunk | null {
  const selectedContent = lines.slice(startLine - 1, endLine).join("\n");
  return (
    chunks.find(
      (chunk) =>
        chunk.file_path === filePath &&
        startLine >= chunk.start_line &&
        endLine <= chunk.end_line &&
        chunk.content.includes(selectedContent),
    ) ?? null
  );
}

function readSourceRefsForContext(context: WikiPageContext): SourceRef[] {
  return readFileEvidenceData(context).sourceRefs;
}

function readFileEvidenceData(context: WikiPageContext): {
  reads: JsonObject[];
  sourceRefs: SourceRef[];
} {
  const reads: JsonObject[] = [];
  const recordedSourceRefs: SourceRef[] = [];
  const repoRoot = resolve(context.repo.path);
  let totalChars = 0;
  for (const ref of prioritizeSourceRefs(
    context.sourceRefs,
    context.request.sourceHints,
  )) {
    if (reads.length >= PAGE_READFILE_LIMIT) {
      break;
    }
    const {
      file_path: filePath,
      start_line: startLine,
      end_line: endLine,
    } = ref;
    const absolutePath = resolve(repoRoot, filePath);
    if (!isPathInside(repoRoot, absolutePath) || !existsSync(absolutePath)) {
      continue;
    }
    try {
      const lines = readFileSync(absolutePath, "utf8").split(/\r?\n/);
      if (startLine < 1 || endLine < startLine || endLine > lines.length) {
        continue;
      }
      const content = numberedLines(lines, startLine, endLine);
      if (
        content.length > PAGE_READFILE_SINGLE_MAX_CHARS ||
        totalChars + content.length > PAGE_READFILE_MAX_CHARS
      ) {
        continue;
      }
      totalChars += content.length;
      reads.push({
        tool_call: "ReadFile",
        file_path: filePath,
        start_line: startLine,
        end_line: endLine,
        content,
      });
      recordedSourceRefs.push({ ...ref, read_via: "ReadFile" });
    } catch {
      // Ignore unreadable files; source_chunks still provide bounded evidence.
    }
  }
  return { reads, sourceRefs: recordedSourceRefs };
}

function mergeReadFileSourceRefs(
  sourceRefs: SourceRef[],
  readSourceRefs: SourceRef[],
  sourceUrlBase: string | null,
): SourceRef[] {
  const merged: SourceRef[] = [];
  const byRange = new Map<string, SourceRef>();
  for (const ref of [...sourceRefs, ...readSourceRefs]) {
    const key = `${ref.file_path}:${ref.start_line}:${ref.end_line}`;
    const existing = byRange.get(key);
    if (existing) {
      if (ref.read_via) {
        existing.read_via = ref.read_via;
      }
      continue;
    }
    const next: SourceRef = { ...ref };
    if (sourceUrlBase && !next.source_url) {
      next.source_url = sourceUrlForRange(
        sourceUrlBase,
        next.file_path,
        next.start_line,
        next.end_line,
      );
    }
    byRange.set(key, next);
    merged.push(next);
  }
  return merged;
}

function stripUnknownCitationMarkers(
  markdown: string,
  sourceRefs: SourceRef[],
): string {
  const validMarkers = new Set(
    sourceRefs
      .map((ref) => ref.citation_id)
      .filter((value): value is string => Boolean(value)),
  );
  return markdown.replace(CITATION_MARKER_RE, (marker, citationId: string) =>
    validMarkers.has(citationId) ? marker : "",
  );
}

function sourceRefHref(ref: SourceRef): string {
  return ref.source_url || "source-link";
}

function sourceFileHref(ref: SourceRef | undefined): string {
  if (!ref?.source_url) {
    return "source-link";
  }
  return ref.source_url.replace(/#L\d+(?:-L\d+)?$/, "");
}

function groupedSourceRefs(
  sourceRefs: SourceRef[],
): Array<[string, SourceRef[]]> {
  const grouped = new Map<string, SourceRef[]>();
  for (const ref of sourceRefs) {
    const refs = grouped.get(ref.file_path) ?? [];
    refs.push(ref);
    grouped.set(ref.file_path, refs);
  }
  return [...grouped.entries()].map(([filePath, refs]) => [
    filePath,
    refs.sort(
      (left, right) =>
        left.start_line - right.start_line || left.end_line - right.end_line,
    ),
  ]);
}

function stripInlineSourcesLines(markdown: string): string {
  const kept: string[] = [];
  let inFence = false;
  for (const line of markdown.split(/\r?\n/)) {
    if (line.trimStart().startsWith("```")) {
      inFence = !inFence;
      kept.push(line);
      continue;
    }
    const trimmed = line.trim();
    if (
      !inFence &&
      !trimmed.startsWith("#") &&
      (INLINE_SOURCES_LINE_RE.test(trimmed) ||
        BOLD_INLINE_SOURCES_LINE_RE.test(trimmed))
    ) {
      continue;
    }
    kept.push(line);
  }
  return kept
    .join("\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function diagramSlotsPayload(diagrams: MermaidDiagram[]): JsonObject[] {
  return diagrams.map((diagram) => ({
    slot: diagram.slot,
    kind: diagram.kind,
    title: diagram.title,
    heading_hint: diagram.headingHint,
  }));
}

function mermaidDiagramsFromContext(
  context: WikiPageContext,
): MermaidDiagram[] {
  const diagrams = [
    componentDiagram(context),
    symbolFlowDiagram(context),
  ].filter((diagram): diagram is MermaidDiagram => Boolean(diagram));
  return diagrams.slice(0, 2);
}

function componentDiagram(context: WikiPageContext): MermaidDiagram | null {
  const files = uniqueStrings(
    context.matchingNodes.map((node) => node.file_path),
  ).slice(0, 8);
  if (!files.length) {
    return null;
  }
  const fileId = new Map(
    files.map((filePath, index) => [filePath, `C${index}`]),
  );
  const lines = ["flowchart TD"];
  for (const filePath of files) {
    lines.push(`  ${fileId.get(filePath)}["${escapeMermaidLabel(filePath)}"]`);
  }
  const nodeById = new Map(
    context.matchingNodes.map((node) => [node.id, node]),
  );
  const edges = context.retrievalTrace.related_edges.slice(0, 12);
  for (const edge of edges) {
    const sourceNode = nodeById.get(stringValue(edge.source) ?? "");
    const targetNode = nodeById.get(stringValue(edge.target) ?? "");
    const sourceFile = sourceNode?.file_path;
    const targetFile = targetNode?.file_path;
    if (!sourceFile || !targetFile || sourceFile === targetFile) {
      continue;
    }
    const sourceId = fileId.get(sourceFile);
    const targetId = fileId.get(targetFile);
    if (sourceId && targetId) {
      lines.push(
        `  ${sourceId} -->|${escapeMermaidLabel(stringValue(edge.type) ?? "relates")}| ${targetId}`,
      );
    }
  }
  return {
    slot: "component",
    kind: "component",
    title: `${context.request.title} component relationships`,
    headingHint: "System Context",
    lines,
  };
}

function symbolFlowDiagram(context: WikiPageContext): MermaidDiagram | null {
  const nodes = context.matchingNodes
    .filter((node) => node.type !== "file" && node.type !== "config")
    .slice(0, 10);
  if (!nodes.length) {
    return null;
  }
  const nodeId = new Map(nodes.map((node, index) => [node.id, `S${index}`]));
  const lines = ["flowchart TD"];
  for (const node of nodes) {
    lines.push(
      `  ${nodeId.get(node.id)}["${escapeMermaidLabel(`${node.name} (${node.type})`)}"]`,
    );
  }
  for (const edge of context.retrievalTrace.related_edges.slice(0, 16)) {
    const sourceId = nodeId.get(stringValue(edge.source) ?? "");
    const targetId = nodeId.get(stringValue(edge.target) ?? "");
    if (sourceId && targetId) {
      lines.push(
        `  ${sourceId} -->|${escapeMermaidLabel(stringValue(edge.type) ?? "uses")}| ${targetId}`,
      );
    }
  }
  return {
    slot: "symbol-flow",
    kind: "symbol_flow",
    title: `${context.request.title} implementation flow`,
    headingHint: "Control Flow",
    lines,
  };
}

function escapeMermaidLabel(value: string): string {
  return value.replace(/["\\]/g, "'").replace(/\|/g, "/");
}

function validateDiagramPlaceholders(
  markdown: string,
  diagrams: MermaidDiagram[],
): string[] {
  const allowedSlots = new Set(diagrams.map((diagram) => diagram.slot));
  const unknown = [...markdown.matchAll(DIAGRAM_SLOT_RE)]
    .map((match) => match[1])
    .filter(
      (slot): slot is string =>
        typeof slot === "string" && !allowedSlots.has(slot),
    );
  return unknown.length
    ? [
        `markdown contains unknown diagram placeholders: ${uniqueStrings(unknown).join(", ")}.`,
      ]
    : [];
}

function placeDiagrams(markdown: string, diagrams: MermaidDiagram[]): string {
  if (!diagrams.length) {
    return markdown
      .replace(FENCED_DIAGRAM_SLOT_RE, "")
      .replace(DIAGRAM_SLOT_RE, "")
      .trim();
  }
  const bySlot = new Map(diagrams.map((diagram) => [diagram.slot, diagram]));
  const used = new Set<string>();
  const replaceSlot = (_marker: string, slot: string) => {
    const diagram = bySlot.get(slot);
    if (!diagram) {
      return "";
    }
    used.add(slot);
    return diagramMarkdown(diagram);
  };
  let placed = markdown.replace(FENCED_DIAGRAM_SLOT_RE, replaceSlot);
  placed = placed.replace(DIAGRAM_SLOT_RE, replaceSlot);
  for (const diagram of diagrams) {
    if (used.has(diagram.slot)) {
      continue;
    }
    placed = insertDiagramNearHeading(placed, diagram);
  }
  return placed.trim();
}

function insertDiagramNearHeading(
  markdown: string,
  diagram: MermaidDiagram,
): string {
  const headings = [
    `## ${diagram.headingHint}`,
    ...(diagram.kind === "component"
      ? ["## Architecture", "## Core Components", "## Purpose and Scope"]
      : [
          "## Control Flow",
          "## Core Workflows",
          "## API Surface",
          "## Purpose and Scope",
        ]),
  ];
  for (const heading of headings) {
    const inserted = insertAfterHeading(
      markdown,
      heading,
      diagramMarkdown(diagram),
    );
    if (inserted !== markdown) {
      return inserted;
    }
  }
  return [markdown.trim(), diagramMarkdown(diagram)]
    .filter(Boolean)
    .join("\n\n");
}

function insertAfterHeading(
  markdown: string,
  heading: string,
  insertion: string,
): string {
  const lines = markdown.split(/\r?\n/);
  const index = lines.findIndex((line) => line.trim() === heading);
  if (index < 0) {
    return markdown;
  }
  let insertAt = index + 1;
  while (insertAt < lines.length && !lines[insertAt]?.trim()) {
    insertAt += 1;
  }
  return [
    ...lines.slice(0, insertAt),
    "",
    insertion,
    "",
    ...lines.slice(insertAt),
  ]
    .join("\n")
    .trim();
}

function diagramMarkdown(diagram: MermaidDiagram): string {
  return [
    `### ${diagram.title}`,
    "",
    "```mermaid",
    ...diagram.lines,
    "```",
  ].join("\n");
}

function unwrapCodeWrappedCitationMarkers(markdown: string): string {
  return markdown.replace(/`(\[\[S\d+]])`/g, "$1");
}

function separateAdjacentCitationMarkers(markdown: string): string {
  return markdown.replace(/(]])(?=\[\[S\d+]])/g, "$1 ");
}

function stripRedundantSourceLabels(markdown: string): string {
  return markdown
    .replace(
      /[（(]\s*[^）)\n]*?(?:\/|\\)[^）)\n]*?(?:第\s*\d+\s*[–-]\s*\d+\s*行|lines?\s+\d+\s*[–-]\s*\d+)\s*(\[\[S\d+]])\s*[）)]/gi,
      " $1",
    )
    .replace(
      /(\[\[S\d+]])\s*[（(]\s*(?:[^）)\n]*?\s+)?(?:第\s*)?\d+\s*[–-]\s*\d+\s*行?\s*[）)]/gi,
      "$1",
    )
    .replace(
      /(\[\[S\d+]])\s*[（(]\s*(?:[^）)\n]*?\s+)?lines?\s+\d+\s*[–-]\s*\d+\s*[）)]/gi,
      "$1",
    )
    .replace(/ {2,}(?=\[\[S\d+]])/g, " ");
}

function draftMarkdown(title: string, errors: string[]): string {
  return [
    `# ${title}`,
    "",
    "This page was not promoted because generation or validation failed.",
    "",
    "## Validation Errors",
    ...errors.map((error) => `- ${error}`),
  ].join("\n");
}

function pageRepairPayload(
  basePayload: JsonObject,
  previousResponse: string,
  validationErrors: string[],
): JsonObject {
  return {
    ...basePayload,
    previous_response: previousResponse.slice(0, 6000),
    validation_errors: validationErrors,
    repair_instructions:
      "Repair the page response. Return one valid JSON object only, with title, markdown, and source_refs. Use source_refs from allowed_source_refs only.",
  };
}

function childPageSummaries(pages: DocPage[]): JsonObject[] {
  return pages.slice(0, 8).map((page) => ({
    title: page.title,
    slug: page.slug,
    status: page.status,
    overview_markdown: firstContentSection(page.markdown).slice(0, 1600),
    source_refs: page.source_refs.slice(0, 6),
    graph_refs: page.graph_refs.slice(0, 12),
  }));
}

function evidenceInventoryPayload(context: WikiPageContext): JsonObject {
  const nodeTypes = uniqueStrings(
    [
      ...context.retrievalTrace.seed_nodes,
      ...context.retrievalTrace.expanded_nodes,
    ].map((node) => stringValue(node.type) ?? "unknown"),
  );
  const edgeTypes = uniqueStrings(
    context.retrievalTrace.related_edges.map(
      (edge) => stringValue(edge.type) ?? "unknown",
    ),
  );
  return {
    counts: {
      seed_nodes: context.retrievalTrace.seed_nodes.length,
      expanded_nodes: context.retrievalTrace.expanded_nodes.length,
      related_edges: context.retrievalTrace.related_edges.length,
      source_chunks: context.matchingChunks.length,
      communities: context.retrievalTrace.community_summaries.length,
    },
    node_types: nodeTypes,
    edge_types: edgeTypes,
    top_files: uniqueStrings(
      context.matchingNodes.map((node) => node.file_path),
    ).slice(0, 12),
  };
}

function sourceChunkMetadata(chunks: CodeChunk[]): JsonObject[] {
  return chunks.map((chunk, index) => ({
    id: chunk.id,
    node_id: chunk.node_id,
    file_path: chunk.file_path,
    start_line: chunk.start_line,
    end_line: chunk.end_line,
    content_hash: chunk.content_hash,
    token_count: chunk.token_count,
    citation_id: `S${index + 1}`,
  }));
}

function readFileEvidence(context: WikiPageContext): JsonObject {
  const reads: JsonObject[] = [];
  const recordedSourceRefs: JsonObject[] = [];
  const repoRoot = resolve(context.repo.path);
  let totalChars = 0;
  for (const ref of prioritizeSourceRefs(
    context.sourceRefs,
    context.request.sourceHints,
  )) {
    if (reads.length >= PAGE_READFILE_LIMIT) {
      break;
    }
    const filePath = stringValue(ref.file_path);
    const startLine = numberValue(ref.start_line);
    const endLine = numberValue(ref.end_line);
    if (!filePath || !startLine || !endLine) {
      continue;
    }
    const absolutePath = resolve(repoRoot, filePath);
    if (!isPathInside(repoRoot, absolutePath) || !existsSync(absolutePath)) {
      continue;
    }
    try {
      const lines = readFileSync(absolutePath, "utf8").split(/\r?\n/);
      if (startLine < 1 || endLine < startLine || endLine > lines.length) {
        continue;
      }
      const content = numberedLines(lines, startLine, endLine);
      if (
        content.length > PAGE_READFILE_SINGLE_MAX_CHARS ||
        totalChars + content.length > PAGE_READFILE_MAX_CHARS
      ) {
        continue;
      }
      totalChars += content.length;
      reads.push({
        tool_call: "ReadFile",
        file_path: filePath,
        start_line: startLine,
        end_line: endLine,
        content,
      });
      recordedSourceRefs.push({
        ...ref,
        read_via: "ReadFile",
      });
    } catch {
      // Ignore unreadable files; source_chunks still provide bounded evidence.
    }
  }
  return {
    tool: "ReadFile",
    required: true,
    description:
      "Server-executed ReadFile evidence. Treat reads as mandatory source material; if reads is empty, say direct source evidence is missing instead of guessing.",
    reads,
    recorded_source_refs: recordedSourceRefs,
  };
}

function prioritizeSourceRefs(
  sourceRefs: SourceRef[],
  sourceHints: string[],
): SourceRef[] {
  if (!sourceHints.length) {
    return sourceRefs;
  }
  const hinted: SourceRef[] = [];
  const other: SourceRef[] = [];
  for (const ref of sourceRefs) {
    const filePath = ref.file_path;
    if (
      sourceHints.some((hint) =>
        pathMatchesHint(filePath, normalizedPath(hint)),
      )
    ) {
      hinted.push(ref);
    } else {
      other.push(ref);
    }
  }
  return [...hinted, ...other];
}

function numberedLines(
  lines: string[],
  startLine: number,
  endLine: number,
): string {
  const width = String(endLine).length;
  const selected: string[] = [];
  for (let lineNumber = startLine; lineNumber <= endLine; lineNumber += 1) {
    selected.push(
      `${String(lineNumber).padStart(width, " ")}: ${lines[lineNumber - 1] ?? ""}`,
    );
  }
  return selected.join("\n");
}

function isPathInside(root: string, target: string): boolean {
  const relativePath = relative(root, target);
  return (
    relativePath === "" ||
    (!relativePath.startsWith("..") && !isAbsolute(relativePath))
  );
}

function graphFactsPayload(trace: RetrievalTrace): JsonObject {
  return {
    seed_nodes: trace.seed_nodes.map(promptNode),
    expanded_nodes: trace.expanded_nodes.map(promptNode),
    related_edges: trace.related_edges.map(promptEdge),
    community_edges: trace.community_edges.map(promptEdge),
    community_summaries: trace.community_summaries.map(promptCommunitySummary),
    community_hierarchy: communityHierarchy(trace.community_summaries),
  };
}

function promptNode(node: JsonObject): JsonObject {
  return compactJsonObject({
    id: node.id,
    type: node.type,
    name: node.name,
    file_path: node.file_path,
    line: lineRange(node),
    hop: node.hop,
    score: node.score,
    confidence: node.confidence,
  });
}

function promptEdge(edge: JsonObject): JsonObject {
  return compactJsonObject({
    id: edge.id,
    source: edge.source,
    target: edge.target,
    type: edge.type,
    confidence: edge.confidence,
    reason: edge.reason,
  });
}

function promptCommunitySummary(community: JsonObject): JsonObject {
  const nodeIds = Array.isArray(community.node_ids)
    ? community.node_ids.filter(
        (value): value is string => typeof value === "string",
      )
    : [];
  return compactJsonObject({
    id: community.id,
    name: community.name,
    level: community.level,
    parent_id: community.parent_id,
    summary: community.summary,
    node_count: numberValue(community.node_count) ?? nodeIds.length,
    matched_node_ids: Array.isArray(community.matched_node_ids)
      ? community.matched_node_ids
      : nodeIds,
  });
}

function communityHierarchy(communities: JsonObject[]): JsonObject[] {
  const byId = new Map<string, JsonObject>();
  const roots: JsonObject[] = [];
  for (const community of communities) {
    const id = stringValue(community.id);
    if (id) {
      byId.set(id, promptCommunitySummary(community));
    }
  }
  for (const community of communities) {
    const id = stringValue(community.id);
    if (!id) {
      continue;
    }
    const item = byId.get(id);
    if (!item) {
      continue;
    }
    const parentId = stringValue(community.parent_id);
    const parent = parentId ? byId.get(parentId) : null;
    if (parent) {
      const children = Array.isArray(parent.children) ? parent.children : [];
      children.push(item);
      parent.children = children;
    } else {
      roots.push(item);
    }
  }
  return roots;
}

function lineRange(item: JsonObject): string | null {
  const startLine = numberValue(item.start_line);
  const endLine = numberValue(item.end_line);
  if (!startLine) {
    return null;
  }
  return endLine && endLine !== startLine
    ? `${startLine}-${endLine}`
    : String(startLine);
}

function compactJsonObject(values: Record<string, unknown>): JsonObject {
  const payload: JsonObject = {};
  for (const [key, value] of Object.entries(values)) {
    if (value === undefined || value === null || value === "") {
      continue;
    }
    if (Array.isArray(value) && !value.length) {
      continue;
    }
    if (isJsonValue(value)) {
      payload[key] = value;
    }
  }
  return payload;
}

function isJsonValue(value: unknown): value is JsonObject[string] {
  if (
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean" ||
    value === null
  ) {
    return true;
  }
  if (Array.isArray(value)) {
    return value.every(isJsonValue);
  }
  return isRecord(value) && Object.values(value).every(isJsonValue);
}

function promptContract(): JsonObject {
  return {
    source_linking: {
      source_refs:
        "Use only file_path/start_line/end_line values from allowed_source_refs.",
      source_urls:
        "The server converts validated source refs into clickable source URLs when repository git metadata is available.",
      inline_citations:
        "Use compact [[S#]] markers after source-grounded claims. Return every used marker in source_refs.",
    },
    citation_style: {
      inline_markers:
        "Use compact [[S#]] markers near concrete claims. The server renders grouped source ranges separately.",
      avoid_noise:
        "Do not repeat long source file labels in prose. Do not add section-level Sources lines.",
    },
    documentation_style: {
      name: "DeepWiki",
      workflow: [
        "GATHER with mandatory ReadFile evidence, source_chunks, and graph_facts",
        "think through subsystem boundaries, lifecycle, contracts, state changes, extension points, and failure paths",
        "write detailed Markdown with compact tables, concrete execution paths, and inline citations",
      ],
      required_sections: [
        "Purpose and Scope",
        "Architecture or System Context when relationships are evidenced",
        "Control Flow or Lifecycle when evidenced",
        "Data Model, API Surface, Configuration, or Failure Handling when evidenced",
        "Extension Points or Operational Notes when change boundaries are evidenced",
      ],
      server_injected_sections: [
        "Relevant source files",
        "validated Mermaid diagrams",
        "grouped Sources",
      ],
      preferred_tables: [
        "component/file/responsibility/evidence",
        "symbol/function/caller/callee/evidence",
        "route or API/symbol/purpose/evidence",
        "data structure/owner/fields or role/evidence",
        "configuration key/default or source/effect/evidence",
        "workflow step/owner/input/output/side effect/evidence",
        "failure mode/trigger/handling/evidence",
        "state transition/current state/trigger/next state/evidence",
        "extension point/current owner/change path/contract/evidence",
      ],
    },
    detail_expectations: {
      minimum_depth:
        "For non-trivial pages, cover responsibility, lifecycle/control flow, dependencies, inputs and outputs, data surfaces, APIs or UI routes, configuration, validation, extension points, failure handling, state transitions, and internal tradeoffs when evidence supports them.",
      section_depth:
        "Implementation pages should have 5-8 substantive sections and at least four evidence-backed detail blocks when evidence is sufficient. Parent pages should synthesize child boundaries and cross-child flow rather than listing children.",
      related_pages:
        "Mention related pages only from catalog_context.related_pages and only when evidence supports the relationship.",
      missing_information:
        "If expected lifecycle, configuration, error handling, or recovery behavior is absent from source evidence, state the gap briefly instead of guessing.",
    },
    diagram_placement: {
      placeholder_format: "[[DIAGRAM:<slot>]]",
      instructions:
        "Use only slots listed in diagram_slots. Do not emit Mermaid; the server generates diagrams from graph facts.",
    },
    agent_tools: {
      available: [
        {
          name: "ReadFile",
          purpose: "Read exact repository source ranges before writing.",
        },
      ],
      required_for_page_generation: ["ReadFile"],
    },
    required_json_shape: {
      title: "Use the exact page title from page_payload.title.",
      markdown:
        "# Page title\n\n## Purpose and Scope\n\nGrounded Markdown with inline [[S1]] citations, optional [[DIAGRAM:slot]] placeholders from diagram_slots, and no Mermaid fences.",
      source_refs: [
        {
          citation_id: "S1",
          file_path: "path.ts",
          start_line: 1,
          end_line: 5,
        },
      ],
    },
  };
}

function pageSystemPrompt(): string {
  return [
    "You are generating one DeepWiki-style Code Wiki page.",
    "You must execute GATHER, THINK, WRITE before answering. Treat readfile_evidence.reads as mandatory ReadFile output. If the mandatory ReadFile evidence does not support a detail, do not present the detail as fact.",
    "In GATHER, inspect the topic, source_hints, source_chunks, graph_facts, catalog_context, and allowed_source_refs to identify the actual files and symbols involved.",
    "In THINK, map subsystem responsibility, dependencies, data/control flow, boundaries, callers, downstream collaborators, and where errors or edge cases are handled. Verify every planned claim against ReadFile evidence, source_chunks, or graph_facts.",
    "In WRITE, produce detailed, source-grounded Markdown as JSON. Favor depth over breadth, but do not add unsupported details.",
    'The markdown must start with "# {title}" and immediately include "## Purpose and Scope" with 1-3 concise paragraphs including the subsystem primary responsibility.',
    "Choose relevant sections from System Context, Core Components, Control Flow, Data Model, API Surface, Configuration, Frontend Flow, Extension Points, Failure Handling, Testing, and Operational Notes.",
    "For non-trivial implementation pages, use 5-8 substantive sections when evidence supports them. Include evidence-backed detail blocks such as component responsibility, workflow, API/data contract, validation/failure-mode, extension point, or configuration tables.",
    "For parent/category pages, synthesize how child pages relate and where shared control flow, data contracts, or dependencies cross child boundaries. Do not simply list child pages.",
    "Every concrete factual claim about code must be supported by ReadFile evidence, source_chunks, or graph_facts, with nearby [[S#]] citation markers from allowed_source_refs.",
    "Prefer citations whose ranges appear in readfile_evidence.recorded_source_refs. If readfile_evidence.reads is empty, say direct source evidence is missing instead of guessing.",
    "Mention related pages only from catalog_context.related_pages. Do not invent wiki links or pages.",
    "Do not include Sources, Relevant source files, Related Pages, On this page, Mermaid sections, or Mermaid code; the server renders those.",
    "If diagram_slots contains a useful diagram, place the exact [[DIAGRAM:<slot>]] placeholder on its own line. Do not invent slots.",
    "Return only JSON with title, markdown, and source_refs.",
  ].join("\n\n");
}

function jsonMessage(title: string, payload: JsonObject): string {
  return `${title}:\n${JSON.stringify(payload, null, 2)}`;
}

function parseJsonObject(
  content: string,
  validationErrors: string[],
): JsonObject | null {
  const trimmed = stripMarkdownFence(content.trim());
  const candidates = [trimmed, extractObject(trimmed)].filter(
    (candidate): candidate is string => Boolean(candidate),
  );
  for (const candidate of candidates) {
    try {
      const parsed = JSON.parse(candidate) as unknown;
      if (isRecord(parsed)) {
        return parsed as JsonObject;
      }
    } catch {
      // Try the next candidate below.
    }
  }
  validationErrors.push("LLM page response was not valid JSON.");
  return null;
}

function stripMarkdownFence(value: string): string {
  const fence = /^```(?:json)?\s*([\s\S]*?)\s*```$/i.exec(value);
  return fence?.[1]?.trim() ?? value;
}

function extractObject(value: string): string | null {
  const start = value.indexOf("{");
  const end = value.lastIndexOf("}");
  return start >= 0 && end > start ? value.slice(start, end + 1) : null;
}

function stripMermaid(markdown: string): string {
  return markdown.replace(MERMAID_FENCE_RE, "").trim();
}

function normalizeCitationLikeMarkers(markdown: string): string {
  return markdown.replace(
    CITATION_LIKE_MARKER_RE,
    (marker, content: string) => {
      if (/^\[\[S\d+]]$/.test(marker)) {
        return marker;
      }
      const citationIds = content.match(/\bS\d+\b/g) ?? [];
      return citationIds.map((citationId) => `[[${citationId}]]`).join(" ");
    },
  );
}

function citationMarkers(markdown: string): string[] {
  return [...markdown.matchAll(CITATION_MARKER_RE)]
    .map((match) => match[1])
    .filter((value): value is string => typeof value === "string");
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function numberValue(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) ? value : null;
}

function recordValue(value: unknown): JsonObject {
  return isRecord(value) ? (value as JsonObject) : {};
}

function stringArrayValue(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

function nonEmptyString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
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
