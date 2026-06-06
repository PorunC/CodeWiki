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
import { dynamicJsonMessage, stableJsonMessage } from "../llm/messages.js";
import {
  sourceUrlBaseForRepo,
  sourceUrlForRange,
} from "../services/sourceUrls.js";
import { loadPrompt } from "../services/prompts.js";
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
import { graphFactsPayload, promptContract } from "./pagePromptTemplate.js";

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

function pageSystemPrompt(): string {
  return loadPrompt("page.md");
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
