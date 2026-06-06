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
import {
  diagramSlotsPayload,
  graphRefsFromTrace,
  mermaidDiagramsFromTrace,
  type MermaidDiagram,
} from "./diagrams.js";
import type { WikiPageResult } from "./payloads.js";

export type WikiPageRequest = {
  repoId: string;
  slug: string;
  languageCode: string;
  title: string;
  kind: "page" | "category";
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
  responsePayload: JsonObject | null;
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

const PAGE_GENERATION_ATTEMPTS = 2;
const PAGE_RETRIEVAL_MAX_HOPS = 3;
const PAGE_SOURCE_LIMIT = 14;
const PAGE_SYMBOL_LIMIT = 40;
const PAGE_READFILE_LIMIT = 14;
const PAGE_READFILE_MAX_CHARS = 32_000;
const PAGE_READFILE_SINGLE_MAX_CHARS = 8_000;
const MAX_SOURCE_HINT_CHUNKS = 10;
const MAX_SOURCE_HINT_CHUNKS_PER_FILE = 3;
const PAGE_CACHE_VERSION = "page:v5";
const PAGE_PROMPT_VERSION = "page:deepwiki:v5";
const CITATION_MARKER_RE = /\[\[(S\d+)]]/g;
const CITATION_LIKE_MARKER_RE = /\[\[(S[^[\]]*)]]/g;
const MERMAID_FENCE_RE = /```mermaid[\s\S]*?```/gi;
const DIAGRAM_SLOT_RE = /^\s*\[\[DIAGRAM:([a-zA-Z0-9_-]+)]]\s*$/gm;
const FENCED_DIAGRAM_SLOT_RE =
  /^[ \t]*`{3,}[ \t]*\n[ \t]*\[\[DIAGRAM:([a-zA-Z0-9_-]+)]][ \t]*\n[ \t]*`{3,}[ \t]*$/gm;
const INLINE_SOURCES_LINE_RE = /^(?:>\s*)?(?:\*\*)?sources?(?:\*\*)?:\s+\S/i;
const BOLD_INLINE_SOURCES_LINE_RE = /^(?:>\s*)?\*\*sources?:\*\*\s+\S/i;
const IGNORED_READFILE_NAMES = new Set([
  "uv.lock",
  "package-lock.json",
  "pnpm-lock.yaml",
  "yarn.lock",
]);

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
      const userPayload = llmInputPayload(context);
      let attemptPayload = userPayload;
      let validationErrors: string[] = [];
      let completion: CachedLlmCompletion | null = null;
      let lastNormalized: NormalizedPage | null = null;
      for (let attempt = 0; attempt < PAGE_GENERATION_ATTEMPTS; attempt += 1) {
        completion = await this.llm.complete(request.repoId, {
          taskType: "page",
          cacheKey: `${PAGE_CACHE_VERSION}:${request.slug}:${context.retrievalTrace.trace_id}:attempt:${attempt + 1}`,
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
        attemptPayload = normalized.responsePayload
          ? pageValidationRepairPayload(
              userPayload,
              normalized.responsePayload,
              validationErrors,
            )
          : pageJsonRepairPayload(
              userPayload,
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
    const catalog = await this.store.getLatestDocCatalog(
      request.repoId,
      request.languageCode,
    );
    const baseTrace = await this.store.saveRetrievalTrace(
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
    const chunks = await this.store.listCodeChunks(request.repoId);
    const retrievalTrace = withSourceHintChunks(
      baseTrace,
      chunks,
      request.sourceHints,
    );
    const pathNodes = nodesForPath(graph.nodes, request.path);
    const traceNodeIds = nodeIdsFromTrace(retrievalTrace);
    const traceNodes = graph.nodes.filter((node) => traceNodeIds.has(node.id));
    const matchingNodes = uniqueNodes([...traceNodes, ...pathNodes]);
    const matchingChunks = uniqueChunks(retrievalTrace.chunks).slice(
      0,
      PAGE_SOURCE_LIMIT,
    );
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
      graph_refs: graphRefsFromTrace(context.retrievalTrace),
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

function withSourceHintChunks(
  trace: RetrievalTrace,
  allChunks: CodeChunk[],
  sourceHints: string[],
): RetrievalTrace {
  const hints = sourceHints.map(normalizedPath).filter(Boolean);
  if (!hints.length) {
    return trace;
  }
  const hintedChunks: CodeChunk[] = [];
  const perFileCounts = new Map<string, number>();
  for (const chunk of allChunks) {
    if (!hints.some((hint) => pathMatchesHint(chunk.file_path, hint))) {
      continue;
    }
    const currentCount = perFileCounts.get(chunk.file_path) ?? 0;
    if (currentCount >= MAX_SOURCE_HINT_CHUNKS_PER_FILE) {
      continue;
    }
    perFileCounts.set(chunk.file_path, currentCount + 1);
    hintedChunks.push(chunk);
    if (hintedChunks.length >= MAX_SOURCE_HINT_CHUNKS) {
      break;
    }
  }
  if (!hintedChunks.length) {
    return trace;
  }
  const chunks = dedupeSourceChunks([...trace.chunks, ...hintedChunks]);
  return {
    ...trace,
    chunks,
    source_chunks: dedupeSourceChunkPayloads([
      ...trace.source_chunks,
      ...hintedChunks.map((chunk) => ({
        id: chunk.id,
        node_id: chunk.node_id,
        file_path: chunk.file_path,
        start_line: chunk.start_line,
        end_line: chunk.end_line,
        content: chunk.content,
        content_hash: chunk.content_hash,
        token_count: chunk.token_count,
        score: 0.45,
        reasons: ["source_hint"],
      })),
    ]),
  };
}

function dedupeSourceChunks(chunks: CodeChunk[]): CodeChunk[] {
  const seen = new Set<string>();
  const deduped: CodeChunk[] = [];
  for (const chunk of chunks) {
    const key = chunk.id || chunkRangeKey(chunk);
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    deduped.push(chunk);
  }
  return deduped;
}

function dedupeSourceChunkPayloads(chunks: JsonObject[]): JsonObject[] {
  const seen = new Set<string>();
  const deduped: JsonObject[] = [];
  for (const chunk of chunks) {
    const key =
      stringValue(chunk.id) ??
      `${stringValue(chunk.file_path) ?? ""}:${numberValue(chunk.start_line) ?? ""}:${numberValue(chunk.end_line) ?? ""}`;
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    deduped.push(chunk);
  }
  return deduped;
}

function chunkRangeKey(chunk: CodeChunk): string {
  return [chunk.file_path, chunk.start_line, chunk.end_line].join(":");
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
  const instruction = [
    "Return only a JSON object.",
    "Do not include Mermaid blocks; the server will generate abstract diagrams from validated graph facts.",
    "source_refs must be selected from allowed_source_refs.",
    "Use [[S#]] citation markers only for source refs you return.",
    "Use catalog_context.related_pages only for real related-page mentions; do not invent wiki pages or links.",
    "Follow the mandatory GATHER, THINK, WRITE workflow, and ground GATHER in readfile_evidence.reads.",
  ].join(" ");
  return [
    {
      role: "system",
      content: pageSystemPrompt(),
    },
    {
      role: "user",
      content: stableJsonMessage("Stable page generation contract", {
        instructions: instruction,
        prompt_contract: promptContract(),
      }),
    },
    {
      role: "user",
      content: stableJsonMessage("Stable repository wiki context", {
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
      content: dynamicJsonMessage(
        "Page payload",
        validationErrors.length
          ? {
              ...pagePayload,
              validation_errors: validationErrors,
              repair_instructions:
                "Repair the previous response. Return only a valid JSON object.",
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
  const childPageSummaries = childPageSummariesPayload(
    context.request.childPages,
  );
  const isParent =
    childPageSummaries.length > 0 || context.request.kind === "category";
  return {
    title: context.request.title,
    slug: context.request.slug,
    path: context.request.path,
    topic: context.request.topic,
    language_code: context.request.languageCode,
    source_hints: context.request.sourceHints,
    catalog_context: catalogContextForPage(context),
    parent_slug: context.request.parentSlug,
    parent_synthesis: {
      has_child_pages: childPageSummaries.length > 0,
      instructions:
        "When child_page_summaries is non-empty, synthesize this parent page primarily from the generated child page overviews. Use source_chunks and graph_facts to ground citations, fill gaps, and avoid unsupported claims rather than re-deriving the whole parent topic from scratch.",
    },
    child_page_summaries: childPageSummaries,
    page_depth_profile: {
      kind: isParent ? "parent_synthesis" : "implementation_deep_dive",
      expected_detail_level: isParent ? "medium_high" : "high",
      evidence_counts: evidenceCounts,
      available_edge_types: availableEdgeTypes,
      available_node_types: availableNodeTypes,
      emphasis: isParent
        ? [
            "synthesize child page responsibilities without duplicating every child detail",
            "explain the section mental model and cross-child relationships",
            "point out integration boundaries and shared data or control flow",
          ]
        : [
            "drill into concrete files, symbols, call paths, and data contracts",
            "include implementation tables for components, workflows, APIs, and failure modes",
            "describe lifecycle steps from entry point through downstream collaborators",
          ],
    },
    diagram_slots: diagramSlotsPayload(
      mermaidDiagramsFromTrace(context.retrievalTrace, context.request.title),
    ),
    evidence_inventory: evidenceInventory,
    context_pack: context.retrievalTrace.context_pack,
    source_chunks: sourceChunkMetadata(context.retrievalTrace.source_chunks),
    allowed_source_refs: context.sourceRefs,
    readfile_evidence: readFileEvidence(context),
    graph_facts: graphFactsPayload(context.retrievalTrace),
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
      responsePayload: null,
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
  const diagrams = mermaidDiagramsFromTrace(
    context.retrievalTrace,
    context.request.title,
  );
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
    responsePayload: parsed,
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
  const seen = new Set<string>();
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
    const key = `${filePath}:${startLine}:${endLine}`;
    if (seen.has(key) || IGNORED_READFILE_NAMES.has(pathBasename(filePath))) {
      continue;
    }
    seen.add(key);
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
      if (content.length > PAGE_READFILE_SINGLE_MAX_CHARS) {
        continue;
      }
      if (totalChars + content.length > PAGE_READFILE_MAX_CHARS) {
        break;
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
  const headings = uniqueStrings([
    `## ${diagram.headingHint}`,
    ...diagramHeadingCandidates(diagram.kind),
    "## Purpose and Scope",
  ]);
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

function diagramHeadingCandidates(kind: MermaidDiagram["kind"]): string[] {
  const candidates: Record<MermaidDiagram["kind"], string[]> = {
    component: [
      "## System Context",
      "## Architecture",
      "## Core Components",
      "## Overview",
    ],
    data_flow: ["## Control Flow", "## Core Workflows", "## System Context"],
    symbol_flow: [
      "## Control Flow",
      "## Core Workflows",
      "## API Surface",
      "## System Context",
    ],
    sequence: ["## Control Flow", "## Core Workflows", "## API Surface"],
    data_model: ["## Data Model", "## Core Components", "## System Context"],
    surface: ["## API Surface", "## Frontend Flow", "## Core Components"],
  };
  return candidates[kind];
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

function pageJsonRepairPayload(
  basePayload: JsonObject,
  previousResponse: string,
  validationErrors: string[],
): JsonObject {
  return {
    ...basePayload,
    previous_response: previousResponse.slice(0, 6000),
    validation_errors: validationErrors,
    repair_instructions:
      "Repair the page response. Return one valid JSON object only, with title, markdown, and source_refs. Use only diagram placeholders listed in diagram_slots. Do not include prose, comments, Markdown fences around the JSON, or trailing commas.",
  };
}

function pageValidationRepairPayload(
  basePayload: JsonObject,
  previousResponse: JsonObject,
  validationErrors: string[],
): JsonObject {
  return {
    ...basePayload,
    previous_response: previousResponse,
    validation_errors: validationErrors,
    repair_instructions:
      "Repair the page so it validates. Keep the same title, include the required Purpose and Scope section, choose source_refs from allowed_source_refs, and only use [[S#]] markers for source_refs you return. Remove any unknown diagram placeholder, or use exact placeholders from diagram_slots.",
  };
}

function childPageSummariesPayload(pages: DocPage[]): JsonObject[] {
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

function sourceChunkMetadata(chunks: JsonObject[]): JsonObject[] {
  const keptKeys = [
    "id",
    "node_id",
    "file_path",
    "start_line",
    "end_line",
    "content_hash",
    "token_count",
    "score",
    "score_components",
    "reasons",
  ];
  return chunks.map((chunk) => {
    const metadata: JsonObject = {};
    for (const key of keptKeys) {
      const value = chunk[key];
      if (value !== undefined) {
        metadata[key] = value;
      }
    }
    return metadata;
  });
}

function readFileEvidence(context: WikiPageContext): JsonObject {
  const reads: JsonObject[] = [];
  const recordedSourceRefs: JsonObject[] = [];
  const repoRoot = resolve(context.repo.path);
  let totalChars = 0;
  const seen = new Set<string>();
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
    const key = `${filePath}:${startLine}:${endLine}`;
    if (seen.has(key) || IGNORED_READFILE_NAMES.has(pathBasename(filePath))) {
      continue;
    }
    seen.add(key);
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
      if (content.length > PAGE_READFILE_SINGLE_MAX_CHARS) {
        continue;
      }
      if (totalChars + content.length > PAGE_READFILE_MAX_CHARS) {
        break;
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
      "Server-executed ReadFile evidence. Treat this as mandatory source material for the GATHER phase and cite it through allowed_source_refs.",
    reads,
    recorded_source_refs: recordedSourceRefs,
  };
}

function pathBasename(filePath: string): string {
  return normalizedPath(filePath).split("/").at(-1) ?? "";
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
        "The server will convert validated source refs into clickable source URLs when repository git metadata is available.",
      inline_citations:
        "Use [[S1]] style markers from allowed_source_refs after source-grounded sentences. The server validates and converts markers to source links.",
    },
    citation_style: {
      inline_markers:
        "Use compact [[S#]] markers near concrete claims. The server renders them as short citations and groups full source ranges separately.",
      avoid_noise:
        "Do not repeat long source file labels in prose. Avoid section-level Sources lines; the server renders grouped source ranges once at the end.",
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
        "Control Flow or Lifecycle when runtime behavior is evidenced",
        "Data Model, API Surface, Configuration, or Failure Handling when evidenced",
        "Extension Points or Operational Notes when change boundaries are evidenced",
      ],
      server_injected_sections: [
        "Relevant source files",
        "validated Mermaid diagrams at requested diagram placeholders or near matching headings",
        "grouped Sources",
      ],
    },
    detail_expectations: {
      minimum_depth:
        "For non-trivial pages, go beyond a summary. Cover responsibility, lifecycle/control flow, dependencies, inputs and outputs, data surfaces, APIs or UI routes, configuration, validation, extension points, failure handling, operational implications, state transitions, and internal tradeoffs when those details are present.",
      section_depth:
        "When evidence is sufficient, implementation pages should have 5-8 substantive sections and at least four evidence-backed detail blocks. Parent pages should synthesize child boundaries, shared contracts, and cross-child data/control flow rather than listing children.",
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
      code_examples:
        "Use exact source snippets only when source_chunks provide them; otherwise prefer prose over invented examples.",
      related_pages:
        "Mention related pages only from catalog_context.related_pages and only when the relationship is supported by the retrieved evidence.",
      missing_information:
        "If a detail is expected but absent from source evidence, state the gap briefly instead of filling it with assumptions.",
      depth_targets: [
        "explain how the subsystem is entered and what it returns or mutates",
        "name important collaborators and why each boundary exists",
        "describe data contracts, persistence records, schemas, DTOs, or component props",
        "trace at least two end-to-end workflows when graph_facts or source_chunks support them",
        "distinguish thin adapters from domain logic and explain handoff points",
        "explain cache, reuse, recomputation, pruning, or persistence behavior when visible",
        "call out validation, retry, fallback, draft/error state, or cleanup behavior",
        "identify extension points and contracts that constrain future changes",
        "include representative tests only when they clarify observable behavior",
      ],
    },
    diagram_placement: {
      placeholder_format: "[[DIAGRAM:<slot>]]",
      instructions:
        "The server generates Mermaid from graph facts. When a listed diagram slot would clarify a section, place the exact placeholder on its own line near the paragraph that introduces that relationship. Do not invent slots. If no slot fits naturally, omit placeholders and the server will place diagrams near matching headings.",
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
    server_diagram_strategy: {
      diagram_generation: "server_generated_from_graph_facts_only",
      llm_must_not_emit_mermaid: true,
      strategies: {
        component: "graph TD for high-level component dependency maps",
        data_flow: "flowchart LR for data moving between components",
        control_flow: "flowchart TD for hierarchical control or route flow",
        symbol_flow:
          "flowchart TD for concrete endpoints, functions, methods, and calls",
        sequence:
          "sequenceDiagram for request/response or multi-agent interactions",
        data_model: "classDiagram for schemas, classes, DTOs, and inheritance",
      },
      grouping:
        "Prefer flexible subsystem/file labels over raw community names when the graph group name is too generic. Diagrams are inserted in context rather than as a fixed Graph section at the end.",
    },
    required_json_shape: {
      title: "Use the exact page title from page_payload.title.",
      markdown:
        "# Page title\n\n## Purpose and Scope\n\nGrounded Markdown with inline [[S1]] citations, optional [[DIAGRAM:slot]] placeholders from diagram_slots, and no Mermaid fences.",
      source_refs: [
        {
          citation_id: "S1",
          file_path: "path.py",
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
    "",
    "You must execute this workflow in three ordered phases before writing. Treat these",
    "phases as a hard contract, not as suggestions:",
    "- GATHER: use `readfile_evidence.reads` as the mandatory ReadFile tool output. Inspect",
    "  the topic, source_hints, source_chunks, graph_facts, and allowed_source_refs to",
    "  identify the actual files and symbols involved. If the mandatory ReadFile evidence",
    "  does not support a detail, do not present the detail as fact.",
    "- THINK: map the subsystem responsibility, dependencies, data/control flow, and",
    "  boundaries. Identify what uses this subsystem, what it uses, what data it moves,",
    "  and where errors or edge cases are handled. Verify every planned claim against",
    "  ReadFile evidence, source_chunks, or graph_facts.",
    "- WRITE: only after GATHER and THINK, produce detailed, source-grounded Markdown and",
    "  return it as JSON. Favor depth over breadth, but do not add unsupported details.",
    "  A useful page should explain how the subsystem actually works internally, not just",
    "  summarize what files exist.",
    "",
    "Page structure:",
    '- The markdown must start with "# {title}".',
    '- Immediately after the title, write "## Purpose and Scope" with 1-3 concise',
    "  paragraphs describing what this page covers and what it intentionally excludes.",
    '- In "Purpose and Scope", include one direct sentence that states the subsystem\'s',
    "  primary responsibility.",
    "- Write like DeepWiki: source-grounded, implementation-aware, and oriented around how",
    "  the subsystem fits into the larger repository. Prefer short paragraphs, compact",
    "  tables, and explicit relationships between files, APIs, data structures, workflows,",
    "  validation paths, and failure/recovery behavior.",
    "- Use tables as a primary presentation format for dense technical information:",
    "  component responsibilities, routes, data shapes, configuration keys, workflows,",
    "  failure modes, extension points, and source-backed comparisons.",
    "- Add inline source citations with the exact `[[S#]]` markers from `allowed_source_refs`",
    "  after concrete claims about files, functions, routes, data models, or control flow.",
    "- Prefer citations whose ranges appear in `readfile_evidence.recorded_source_refs`.",
    "  Those refs are automatically recorded as files read by the page-generation tool.",
    "- Every concrete factual claim should have at least one nearby citation marker. Prefer",
    "  the narrowest available source range from `allowed_source_refs`; avoid citing a broad",
    "  chunk when a smaller cited chunk supports the claim.",
    "- Use compact inline `[[S#]]` markers. Do not repeat long file/range labels in prose,",
    "  and do not add section-level `Sources:` lines; the server renders grouped source",
    "  ranges once at the end of the page.",
    '- Then choose the most relevant sections from: "System Context", "Core Components",',
    '  "Control Flow", "Data Model", "API Surface", "Configuration", "Frontend Flow",',
    '  "Extension Points", "Failure Handling", "Testing", and "Operational Notes".',
    "- For non-trivial implementation pages, use 5-8 substantive sections when evidence",
    "  supports them. A page with only Purpose, Overview, and Sources is too shallow unless",
    "  the retrieved evidence is genuinely minimal.",
    "- Use compact tables when they make ownership, files, symbols, routes, or data shapes",
    "  easier to scan.",
    "- For implementation pages, include at least four evidence-backed detail blocks when",
    "  evidence permits: a component/symbol responsibility table, an end-to-end workflow",
    "  table, an API/data contract table, a validation/failure-mode table, or an extension",
    "  point/configuration table.",
    "- For parent/category pages, synthesize how child pages relate and where shared",
    "  control flow, data contracts, or dependencies cross child boundaries. Explain what",
    "  responsibility stays in each child, what flows across the boundary, and why the",
    "  split matters. Do not simply list child pages.",
    "- Name concrete files, functions, classes, endpoints, models, and relationships from",
    "  the provided context. Avoid generic tutorial prose.",
    "- When catalog_context contains related pages, mention only directly related pages by",
    "  their provided titles or paths. Do not invent wiki links or pages.",
    '- Do not include "Sources", "Relevant source files", "Related Pages", or Mermaid',
    "  sections; the server and frontend inject those from validated source references,",
    "  catalog context, and graph edges.",
    "- The server chooses Mermaid diagrams from graph facts only. It may use component",
    "  maps, concrete symbol-level implementation flows, left-to-right data flow, top-down",
    "  control flow, sequence diagrams, public surface maps, and class diagrams. Write the",
    "  prose so those diagrams are introduced naturally, but do not emit Mermaid code.",
    "- If `diagram_slots` contains a diagram that clarifies a section, place the exact",
    "  `[[DIAGRAM:<slot>]]` placeholder on its own line inside that section, near the",
    "  paragraph or table that introduces the relationship. Use only slots listed in",
    "  `diagram_slots`; do not invent diagram placeholders. If none fits naturally, omit",
    "  placeholders and the server will place diagrams near matching headings.",
    '- Do not include an "On this page" section; the frontend derives it from headings.',
    "",
    "Detail requirements:",
    "- Cover the subsystem lifecycle or control flow when the evidence shows one.",
    "- Trace at least two concrete end-to-end paths when evidence permits, such as request",
    "  entry to service orchestration to persistence, CLI invocation to graph mutation, or",
    "  UI action to API call to rendered state.",
    "- Explain internal mechanics and tradeoffs: ownership boundaries, why data is shaped",
    "  the way it is, what is cached or reused, what gets recomputed, and which operations",
    "  are intentionally thin adapters versus domain logic.",
    "- Describe upstream dependencies, downstream consumers, and important boundary points.",
    "- Identify data structures, persisted records, DTOs, request/response shapes, or",
    "  configuration keys when they are present in source_chunks or graph_facts.",
    "- Explain important failure modes, validation behavior, retries, draft/error states,",
    "  or fallback paths when the source evidence includes them.",
    "- Explain important invariants and state transitions when they are visible, including",
    "  what is read, written, cached, translated, rendered, retried, or pruned.",
    "- Call out coupling and extension points: which modules can change independently,",
    "  which shared contracts constrain changes, and where new behavior would naturally be",
    "  added when source evidence supports that inference.",
    "- When graph_facts include concrete calls, routes, imports, or inheritance, narrate",
    "  the key path in prose before or after the matching diagram placeholder.",
    "- For API or frontend pages, include route/component/action tables when supported by",
    "  the retrieved context.",
    "- For service or pipeline pages, include a component/responsibility/evidence table.",
    "- For persistence-heavy pages, include record/repository/state-transition tables when",
    "  the retrieved evidence exposes storage behavior.",
    "- For orchestration-heavy pages, include step-by-step execution tables that show",
    "  owner, input, output, side effect, and failure behavior.",
    "- Use tests as evidence for behavior only when they are present in the retrieved",
    "  context; do not let tests dominate a non-testing page.",
    "- If expected information is not visible in the provided source evidence, say so",
    "  briefly instead of guessing. Missing evidence is useful information: add a short",
    '  "Missing evidence:" note when expected lifecycle, configuration, error handling, or',
    "  recovery behavior is not exposed by the retrieved source.",
    "",
    "Rules:",
    "- Every factual claim about code must be supported by ReadFile evidence, source chunks,",
    "  or graph edges.",
    "- Do not ignore the mandatory ReadFile evidence. If readfile_evidence.reads is empty,",
    "  say that direct source evidence is missing instead of guessing.",
    "- Code examples must come from source chunks or be explicitly marked as pseudocode.",
    "- Prefer no code examples over fabricated examples. If including code, use exact code",
    "  from source_chunks and cite it through source_refs.",
    "- Every code block copied from source must have a nearby citation marker. Do not invent",
    "  examples, signatures, request payloads, or configuration defaults.",
    "- source_refs must include the exact file ranges used for the page and must be chosen",
    "  from allowed_source_refs. You may provide only `citation_id` when it exactly matches",
    "  an allowed source ref.",
    "- Do not use citation markers that are absent from the returned source_refs array.",
    "- Return only JSON in the requested shape.",
  ].join("\n");
}

function stableJsonMessage(label: string, payload: JsonObject): string {
  return `${label}:\n${stableJson(payload)}`;
}

function dynamicJsonMessage(label: string, payload: JsonObject): string {
  return `${label}:\n${JSON.stringify(payload)}`;
}

function stableJson(value: unknown): string {
  if (Array.isArray(value)) {
    return `[${value.map(stableJson).join(",")}]`;
  }
  if (value && typeof value === "object") {
    return `{${Object.entries(value)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, nested]) => `${JSON.stringify(key)}:${stableJson(nested)}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

function parseJsonObject(
  content: string,
  validationErrors: string[],
): JsonObject | null {
  const trimmed = stripMarkdownFence(content.trim());
  try {
    const parsed = JSON.parse(trimmed) as unknown;
    if (isRecord(parsed)) {
      return parsed as JsonObject;
    }
    validationErrors.push("LLM response must be a JSON object.");
    return null;
  } catch {
    const candidate = extractObject(trimmed);
    if (!candidate) {
      validationErrors.push("LLM did not return a JSON object.");
      return null;
    }
    try {
      const parsed = JSON.parse(candidate) as unknown;
      if (isRecord(parsed)) {
        return parsed as JsonObject;
      }
      validationErrors.push("LLM response must be a JSON object.");
      return null;
    } catch (nestedError) {
      validationErrors.push(malformedJsonError(nestedError));
      return null;
    }
  }
}

function malformedJsonError(error: unknown): string {
  if (error instanceof SyntaxError) {
    const message =
      error.message.match(/JSON\.parse: (.+)$/)?.[1] ?? error.message;
    return `LLM returned malformed JSON: ${message}.`;
  }
  return "LLM returned malformed JSON.";
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
