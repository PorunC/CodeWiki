import type { CodeWikiStoreApi } from "../db/types.js";
import { notFoundError } from "../errors.js";
import { buildRetrievalTrace } from "../graphrag/retrieval.js";
import {
  LlmCallError,
  type CachedLlmCompletion,
  type LlmOperation,
} from "../llm/cache.js";
import type {
  CodeChunk,
  CodeGraphEdge,
  CodeGraphNode,
  DocCatalog,
  GraphCommunity,
  JsonObject,
  RepoDescriptor,
  RetrievalTrace,
} from "../types.js";
import {
  buildCatalogItems,
  catalogStructure,
  catalogTitle,
  slugify,
  type CatalogItem,
} from "./catalog.js";
import type { WikiCatalogResult } from "./payloads.js";

export type WikiCatalogRequest = {
  repoId: string;
  languageCode: string;
};

type WikiCatalogLlm = {
  isConfigured(taskType: string): boolean;
  complete(
    repoId: string,
    operation: LlmOperation,
  ): Promise<CachedLlmCompletion>;
};

type WikiCatalogContext = {
  repo: RepoDescriptor;
  request: WikiCatalogRequest;
  nodes: CodeGraphNode[];
  edges: CodeGraphEdge[];
  chunks: CodeChunk[];
  communities: GraphCommunity[];
  retrievalTrace: RetrievalTrace;
  localItems: CatalogItem[];
};

type CatalogDraft = {
  title: string;
  items: CatalogItem[];
};

type NormalizedCatalog = CatalogDraft & {
  validationErrors: string[];
};

const MAX_CATALOG_ITEMS = 80;
const MAX_CATALOG_DEPTH = 4;
const CATALOG_GENERATION_ATTEMPTS = 3;
const CATALOG_RETRIEVAL_LIMIT = 18;
const CATALOG_PROMPT_VERSION = "ts-wiki-catalog-deepwiki-v2";

type CatalogScaleProfile = {
  scale: string;
  target_top_level_sections: string;
  target_total_pages: string;
  target_depth: string;
  max_top_level_items: number;
  max_total_items: number;
  max_children_per_item: number;
  max_depth: number;
};

type CatalogScale = CatalogScaleProfile & {
  metrics: JsonObject;
  hard_limits: JsonObject;
};

const CATALOG_SCALE_PROFILES: readonly [
  CatalogScaleProfile,
  ...CatalogScaleProfile[],
] = [
  {
    scale: "tiny",
    target_top_level_sections:
      "4-6 high-signal sections including required special pages",
    target_total_pages: "4-8 focused pages; keep tiny repositories compact",
    target_depth: "1-2 levels; avoid drill-down pages unless evidence is strong",
    max_top_level_items: 8,
    max_total_items: 10,
    max_children_per_item: 6,
    max_depth: 2,
  },
  {
    scale: "small",
    target_top_level_sections:
      "5-8 high-signal sections including required special pages",
    target_total_pages: "8-16 focused pages; split only clear subsystems",
    target_depth: "2 levels for most areas; use 3 only for clear boundaries",
    max_top_level_items: 10,
    max_total_items: 22,
    max_children_per_item: 8,
    max_depth: 3,
  },
  {
    scale: "medium",
    target_top_level_sections:
      "6-10 high-signal sections including required special pages",
    target_total_pages:
      "16-32 focused pages; use fewer only when evidence is genuinely small",
    target_depth: "2-3 levels for complex areas; never deeper than 4 levels",
    max_top_level_items: 12,
    max_total_items: 40,
    max_children_per_item: 12,
    max_depth: 4,
  },
  {
    scale: "large",
    target_top_level_sections:
      "8-12 high-signal sections including required special pages",
    target_total_pages:
      "28-56 focused pages; split major workflows and public surfaces",
    target_depth: "2-3 levels; use 4 only for strongly evidenced subsystems",
    max_top_level_items: 14,
    max_total_items: 72,
    max_children_per_item: 14,
    max_depth: 4,
  },
  {
    scale: "xlarge",
    target_top_level_sections:
      "10-14 high-signal sections including required special pages",
    target_total_pages:
      "44-88 focused pages; prefer subsystem drill-downs over broad pages",
    target_depth:
      "3 levels for complex areas; use 4 only where graph boundaries are clear",
    max_top_level_items: 16,
    max_total_items: 110,
    max_children_per_item: 16,
    max_depth: 4,
  },
];

export class WikiCatalogGenerator {
  constructor(
    private readonly store: CodeWikiStoreApi,
    private readonly llm?: WikiCatalogLlm,
  ) {}

  async generate(request: WikiCatalogRequest): Promise<DocCatalog> {
    return this.saveCatalog(await this.catalogContext(request), (context) =>
      localCatalogDraft(context),
    );
  }

  async generateWithLlmFallback(
    request: WikiCatalogRequest,
  ): Promise<WikiCatalogResult> {
    const context = await this.catalogContext(request);
    const localDraft = localCatalogDraft(context);
    if (!this.llm?.isConfigured("catalog") || !context.nodes.length) {
      return {
        catalog: await this.saveCatalog(context, () => localDraft),
        validation_errors: [],
      };
    }

    try {
      const userPayload = llmInputPayload(context);
      let attemptPayload = userPayload;
      let validationErrors: string[] = [];
      let completion: CachedLlmCompletion | null = null;
      for (let attempt = 0; attempt < CATALOG_GENERATION_ATTEMPTS; attempt += 1) {
        completion = await this.llm.complete(request.repoId, {
          taskType: "catalog",
          cacheKey: `wiki-catalog:${request.languageCode}:${context.retrievalTrace.trace_id}:attempt:${attempt + 1}`,
          modelAlias: "catalog",
          promptVersion: CATALOG_PROMPT_VERSION,
          inputPayload: attemptPayload,
          messages: wikiCatalogMessages(attemptPayload, validationErrors),
          completion: { responseFormat: "json_object" },
        });
        const normalized = normalizeCatalogCompletion(
          completion.result.content,
          localDraft,
        );
        validationErrors = normalized.validationErrors;
        if (normalized.items.length) {
          return {
            catalog: await this.saveCatalog(context, () => normalized),
            validation_errors: validationErrors,
            llm: llmMetadata("success", completion),
          };
        }
        await this.store.updateLlmRunStatus(completion.run.id, {
          status: "error",
          error: validationErrors.join("; ") || "Empty catalog.",
        });
        attemptPayload = catalogRepairPayload(
          userPayload,
          completion.result.content,
          validationErrors,
        );
      }

      return {
        catalog: await this.saveCatalog(context, () => localDraft),
        validation_errors: validationErrors,
        llm: {
          status: "fallback",
          error:
            validationErrors.join("; ") ||
            "LLM did not return a valid catalog.",
          run_id: completion?.run.id ?? null,
        },
      };
    } catch (error) {
      return {
        catalog: await this.saveCatalog(context, () => localDraft),
        validation_errors: [],
        llm: {
          status: "fallback",
          error: error instanceof Error ? error.message : String(error),
          run_id: error instanceof LlmCallError ? error.runId : null,
        },
      };
    }
  }

  private async catalogContext(
    request: WikiCatalogRequest,
  ): Promise<WikiCatalogContext> {
    const repo = await this.store.getRepo(request.repoId);
    if (!repo) {
      throw notFoundError("Repository", request.repoId);
    }
    const graph = await this.store.getGraph(request.repoId);
    const chunks = await this.store.listCodeChunks(request.repoId);
    const retrievalTrace = await this.store.saveRetrievalTrace(
      await buildRetrievalTrace(this.store, request.repoId, "repository overview", {
        maxHops: 3,
        limit: CATALOG_RETRIEVAL_LIMIT,
      }),
    );
    return {
      repo,
      request,
      nodes: graph.nodes,
      edges: graph.edges,
      chunks,
      communities: await this.store.listGraphCommunities(request.repoId),
      retrievalTrace,
      localItems: buildCatalogItems(graph.nodes),
    };
  }

  private async saveCatalog(
    context: WikiCatalogContext,
    draft: (context: WikiCatalogContext) => CatalogDraft,
  ): Promise<DocCatalog> {
    const catalog = draft(context);
    return this.store.saveDocCatalog(context.request.repoId, {
      language_code: context.request.languageCode,
      title: catalog.title,
      structure: catalogStructure(catalog.items),
    });
  }
}

function localCatalogDraft(context: WikiCatalogContext): CatalogDraft {
  return {
    title: catalogTitle(context.repo.name),
    items: context.localItems,
  };
}

function wikiCatalogMessages(
  payload: JsonObject,
  validationErrors: string[] = [],
): LlmOperation["messages"] {
  return [
    {
      role: "system",
      content: catalogSystemPrompt(),
    },
    {
      role: "user",
      content: jsonMessage("Stable catalog generation contract", {
        instructions: validationErrors.length
          ? `Repair the previous response. Validation errors: ${JSON.stringify(validationErrors)}`
          : "Return only a valid JSON object with title and items. Do not include Markdown fences, comments, trailing commas, or prose outside JSON.",
      }),
    },
    {
      role: "user",
      content: jsonMessage("Catalog payload", payload),
    },
  ];
}

function llmInputPayload(context: WikiCatalogContext): JsonObject {
  const scale = catalogScale(context);
  const files = context.nodes
    .filter((node) => node.type === "file" || node.type === "config")
    .sort((left, right) => left.file_path.localeCompare(right.file_path))
    .slice(0, 120)
    .map((node) => ({
      file_path: node.file_path,
      type: node.type,
      language: node.language,
    }));
  const symbols = context.nodes
    .filter((node) => node.type !== "file" && node.type !== "config")
    .slice(0, 120)
    .map((node) => ({
      name: node.name,
      type: node.type,
      file_path: node.file_path,
      language: node.language,
    }));
  return {
    repo: {
      id: context.repo.id,
      name: context.repo.name,
      path: context.repo.path,
      git_url: context.repo.git_url,
      commit_hash: context.repo.commit_hash,
      source_type: context.repo.source_type,
    },
    repo_name: context.repo.name,
    language_code: context.request.languageCode,
    local_title: catalogTitle(context.repo.name),
    local_items: context.localItems,
    documentation_style: {
      name: "DeepWiki",
      shape:
        "hierarchical developer wiki with Overview first, subsystem pages, workflow drill-downs, and source-grounded topics",
      preferred_top_level_flow: [
        "Overview",
        "Architecture",
        "Reading Guide",
        "Dependencies",
        "Getting Started or User Guide",
        "Core Workflows",
        "API Reference",
        "Developer Guide",
        "Operations",
      ],
      catalog_design: [
        "group related files and symbols into logical feature or subsystem pages",
        "use parent categories for navigation and leaf pages for implementation detail",
        "avoid file-by-file catalogs unless a file is the public surface",
        "exclude tests, docs, generated output, and scaffolding from core pages unless explicitly scoped",
      ],
    },
    catalog_scale: scale,
    granularity_contract: granularityContract(scale),
    catalog_design_requirements: {
      required_special_pages: [
        "Overview",
        "Architecture",
        "Reading Guide",
        "Dependencies",
      ],
      coverage: [
        "runtime entry points and bootstrapping",
        "public API or UI surfaces",
        "core services, workflows, pipelines, and background jobs",
        "data models, persistence, schemas, and migrations",
        "configuration, deployment, and operational concerns when evidenced",
      ],
      source_hint_priorities: [
        "P0 primary implementation files",
        "P1 public contracts, schemas, routes, and UI entry points",
        "P2 configuration and environment files",
        "P3 representative tests only when they clarify behavior",
      ],
    },
    repository_context: repositoryContext(context),
    module_candidates: moduleCandidates(context.nodes, context.edges),
    context_pack: catalogContextPack(context.retrievalTrace.context_pack),
    seed_nodes: context.retrievalTrace.seed_nodes,
    expanded_nodes: context.retrievalTrace.expanded_nodes.slice(0, 80),
    community_edges: context.retrievalTrace.community_edges,
    community_summaries: context.retrievalTrace.community_summaries,
    source_chunks: sourceChunkSummaries(context.retrievalTrace.chunks),
    files,
    symbols,
    communities: context.communities.slice(0, 40).map((community) => ({
      id: community.id,
      name: community.name,
      level: community.level,
      rank: community.rank,
      summary: community.summary,
    })),
    required_json_shape: {
      title: "Code Wiki",
      items: [
        {
          title: "Overview",
          slug: "overview",
          path: "overview",
          order: 0,
          kind: "page",
          topic: "repository overview",
          source_hints: ["README.md"],
          children: [],
        },
        {
          title: "Architecture",
          slug: "architecture",
          path: "architecture",
          order: 1,
          kind: "page",
          topic:
            "repository architecture, runtime entry points, major subsystems, and dependencies",
          source_hints: [],
          children: [],
        },
      ],
    },
  };
}

function normalizeCatalogCompletion(
  content: string,
  fallback: CatalogDraft,
): NormalizedCatalog {
  const validationErrors: string[] = [];
  const parsed = parseJsonObject(content, validationErrors);
  if (!parsed) {
    return { ...fallback, items: [], validationErrors };
  }
  const rawItems = parsed.items;
  if (!Array.isArray(rawItems)) {
    validationErrors.push("Catalog JSON must include an items array.");
    return { ...fallback, items: [], validationErrors };
  }
  const usedSlugs = new Set<string>();
  const items = normalizeItems(rawItems, {
    depth: 0,
    usedSlugs,
    validationErrors,
    remaining: { count: MAX_CATALOG_ITEMS },
  });
  const title = nonEmptyString(parsed.title) ?? fallback.title;
  return { title, items, validationErrors };
}

function catalogRepairPayload(
  basePayload: JsonObject,
  previousResponse: string,
  validationErrors: string[],
): JsonObject {
  return {
    ...basePayload,
    previous_response: previousResponse.slice(0, 6000),
    validation_errors: validationErrors,
    repair_instructions:
      "Repair the catalog. Return valid JSON only, with a top-level object containing title and items. Do not include Markdown or comments.",
  };
}

function catalogSystemPrompt(): string {
  return [
    "You are generating a DeepWiki-style Code Wiki catalog from a repository graph and repository context.",
    "Read the repository context, compact module candidates, graph evidence, source chunks, and local fallback items before deciding pages.",
    "Build a navigable documentation tree, not a flat list of file summaries. Start with high-signal orientation pages when evidenced, then group pages by real systems, layers, workflows, data models, APIs, services, frontend surfaces, and operational concerns.",
    "Use parent categories for navigation and leaf pages for implementation detail. Leaf pages should have focused source_hints and a topic that is a retrieval query naming concrete files, symbols, APIs, workflows, or configuration.",
    "Use module_candidates as a shortlist of directories and symbol clusters that deserve splitting. Avoid file-by-file catalogs unless a file is the public surface.",
    "Exclude tests, docs, generated output, and scaffolding from core feature pages unless the page is explicitly about those concerns.",
    "Return only JSON with title and items. Catalog item fields are title, slug, path, order, kind, topic, source_hints, and children.",
  ].join("\n\n");
}

function catalogScale(context: WikiCatalogContext): CatalogScale {
  const fileCount = fileCountForNodes(context.nodes);
  const nodeCount = context.nodes.length;
  const edgeCount = context.edges.length;
  const chunkCount = context.chunks.length;
  const communityCount = context.communities.length;
  const bucketIndex = Math.max(
    bucket(fileCount, [12, 40, 120, 300]),
    bucket(nodeCount, [80, 250, 800, 2000]),
    bucket(edgeCount, [120, 500, 1800, 5000]),
    bucket(chunkCount, [30, 120, 350, 900]),
    bucket(communityCount, [4, 12, 30, 80]),
  );
  const profile =
    CATALOG_SCALE_PROFILES[
      Math.min(bucketIndex, CATALOG_SCALE_PROFILES.length - 1)
    ] ?? CATALOG_SCALE_PROFILES[0];
  return {
    ...profile,
    metrics: {
      file_count: fileCount,
      node_count: nodeCount,
      edge_count: edgeCount,
      chunk_count: chunkCount,
      community_count: communityCount,
    },
    hard_limits: {
      max_top_level_items: profile.max_top_level_items,
      max_total_items: profile.max_total_items,
      max_children_per_item: profile.max_children_per_item,
      max_depth: profile.max_depth,
    },
  };
}

function granularityContract(scale: CatalogScale): JsonObject {
  return {
    target_top_level_sections: scale.target_top_level_sections,
    target_total_pages: scale.target_total_pages,
    target_depth: scale.target_depth,
    split_triggers: [
      "a directory or subsystem owns 3+ source files",
      "a module mixes routes/controllers, services, models, configuration, and UI",
      "a workflow has separate ingestion, planning, execution, validation, and rendering stages",
      "a public API or UI surface has multiple screens, endpoints, commands, or export formats",
      "a data layer has separate schema, repositories, persistence, migrations, or caching concerns",
    ],
    leaf_page_scope:
      "Each leaf should cover one concrete subsystem, workflow stage, public surface, data contract family, UI view, provider integration, export format, CLI/automation flow, or extension point with narrow source_hints.",
    anti_patterns: [
      "one huge Backend page that hides services, API routes, data models, and background jobs",
      "one huge Frontend page that hides pages, hooks, rendering, graph UI, wiki UI, and exports",
      "thin one-file pages for private helpers that should be part of a nearby workflow page",
    ],
  };
}

function repositoryContext(context: WikiCatalogContext): JsonObject {
  const files: string[] = uniqueStrings(
    context.nodes
      .filter((node) => node.type === "file" || node.type === "config")
      .map((node) => node.file_path),
  ).sort((left, right) => left.localeCompare(right));
  return {
    entry_points: files
      .filter((filePath) => /(^|\/)(package\.json|pyproject\.toml|README\.md|Makefile|Dockerfile|vite\.config|tsconfig|main|index|cli|server)/i.test(filePath))
      .slice(0, 40),
    compact_tree: compactTree(files),
    top_level_directories: uniqueStrings(
      files.map((filePath) => filePath.split("/")[0] ?? filePath),
    ).slice(0, 40),
  };
}

function fileCountForNodes(nodes: CodeGraphNode[]): number {
  return uniqueStrings(
    nodes
      .filter((node) => node.type === "file" || node.type === "config")
      .map((node) => node.file_path),
  ).length;
}

function bucket(value: number, thresholds: number[]): number {
  const index = thresholds.findIndex((threshold) => value <= threshold);
  return index === -1 ? thresholds.length : index;
}

function compactTree(files: string[]): JsonObject {
  const root: Record<string, unknown> = {};
  for (const filePath of files.slice(0, 400)) {
    const parts = filePath.split("/").filter(Boolean);
    let current = root;
    parts.forEach((part, index) => {
      if (index === parts.length - 1) {
        const filesForDirectory = current._files;
        current._files = Array.isArray(filesForDirectory)
          ? [...filesForDirectory, part]
          : [part];
        return;
      }
      const child = current[part];
      if (isRecord(child)) {
        current = child;
        return;
      }
      const next: Record<string, unknown> = {};
      current[part] = next;
      current = next;
    });
  }
  return toJsonObject(root);
}

function toJsonObject(value: Record<string, unknown>): JsonObject {
  const result: JsonObject = {};
  for (const [key, rawValue] of Object.entries(value)) {
    if (Array.isArray(rawValue)) {
      result[key] = rawValue.filter(
        (item): item is string => typeof item === "string",
      );
    } else if (isRecord(rawValue)) {
      result[key] = toJsonObject(rawValue);
    }
  }
  return result;
}

function modulePathForFile(filePath: string): string {
  const parts = filePath.split("/").filter(Boolean);
  if (parts.length <= 1) {
    return "root";
  }
  if (parts.length <= 3) {
    return parts.slice(0, -1).join("/");
  }
  return parts.slice(0, 3).join("/");
}

function increment(values: Map<string, number>, key: string): void {
  values.set(key, (values.get(key) ?? 0) + 1);
}

function topEntries(values: Map<string, number>, limit: number): JsonObject[] {
  return [...values.entries()]
    .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))
    .slice(0, limit)
    .map(([name, count]) => ({ name, count }));
}

function splitHint(
  modulePath: string,
  files: string[],
  nodeTypes: Map<string, number>,
): string {
  const symbolCount = [...nodeTypes.entries()]
    .filter(([type]) => type !== "file" && type !== "config")
    .reduce((total, [, count]) => total + count, 0);
  if (files.length >= 8 || symbolCount >= 20) {
    return `${modulePath} is large enough for multiple focused pages.`;
  }
  if (files.length >= 3 || symbolCount >= 8) {
    return `${modulePath} may deserve a focused subsystem page.`;
  }
  return `${modulePath} is likely best covered inside a nearby workflow or overview page.`;
}

function moduleCandidates(
  nodes: CodeGraphNode[],
  edges: CodeGraphEdge[],
): JsonObject[] {
  const groups = new Map<
    string,
    {
      files: Set<string>;
      nodeTypes: Map<string, number>;
      edgeTypes: Map<string, number>;
      symbols: JsonObject[];
    }
  >();
  const nodeModule = new Map<string, string>();
  for (const node of nodes) {
    if (!node.file_path) {
      continue;
    }
    const modulePath = modulePathForFile(node.file_path);
    nodeModule.set(node.id, modulePath);
    const group =
      groups.get(modulePath) ??
      {
        files: new Set<string>(),
        nodeTypes: new Map<string, number>(),
        edgeTypes: new Map<string, number>(),
        symbols: [],
      };
    group.files.add(node.file_path);
    increment(group.nodeTypes, node.type);
    if (node.type !== "file" && node.type !== "config" && group.symbols.length < 18) {
      group.symbols.push({
        name: node.name,
        type: node.type,
        file_path: node.file_path,
      });
    }
    groups.set(modulePath, group);
  }
  for (const edge of edges) {
    const sourceModule = nodeModule.get(edge.source_id);
    const targetModule = nodeModule.get(edge.target_id);
    if (!sourceModule || sourceModule !== targetModule) {
      continue;
    }
    const group = groups.get(sourceModule);
    if (group) {
      increment(group.edgeTypes, edge.type);
    }
  }
  return [...groups.entries()]
    .map(([path, group]) => {
      const files = [...group.files].sort((left, right) =>
        left.localeCompare(right),
      );
      return {
        path,
        file_count: files.length,
        files: files.slice(0, 12),
        node_types: topEntries(group.nodeTypes, 8),
        edge_types: topEntries(group.edgeTypes, 8),
        symbols: group.symbols,
        split_hint: splitHint(path, files, group.nodeTypes),
      };
    })
    .sort(
      (left, right) =>
        numberValue(right.file_count) - numberValue(left.file_count) ||
        stringValue(left.path).localeCompare(stringValue(right.path)),
    )
    .slice(0, 36);
}

function catalogContextPack(contextPack: JsonObject): JsonObject {
  const keys = [
    "token_count",
    "node_count",
    "edge_count",
    "chunk_count",
    "community_count",
    "source_chunk_ids",
    "node_ids",
    "edge_ids",
    "community_ids",
  ];
  const compact: JsonObject = {};
  for (const key of keys) {
    const value = contextPack[key];
    if (value !== undefined) {
      compact[key] = value;
    }
  }
  return compact;
}

function sourceChunkSummaries(chunks: CodeChunk[]): JsonObject[] {
  return chunks.slice(0, CATALOG_RETRIEVAL_LIMIT).map((chunk) => ({
    id: chunk.id,
    node_id: chunk.node_id,
    file_path: chunk.file_path,
    start_line: chunk.start_line,
    end_line: chunk.end_line,
    content_hash: chunk.content_hash,
    token_count: chunk.token_count,
    preview: chunk.content.slice(0, 1200),
  }));
}

function jsonMessage(title: string, payload: JsonObject): string {
  return `${title}:\n${JSON.stringify(payload, null, 2)}`;
}

function uniqueStrings(values: string[]): string[] {
  return [...new Set(values.map((value) => value.trim()).filter(Boolean))];
}

function normalizeItems(
  values: unknown[],
  options: {
    depth: number;
    usedSlugs: Set<string>;
    validationErrors: string[];
    remaining: { count: number };
  },
): CatalogItem[] {
  if (options.depth >= MAX_CATALOG_DEPTH || options.remaining.count <= 0) {
    return [];
  }
  const items: CatalogItem[] = [];
  values.forEach((value, index) => {
    if (options.remaining.count <= 0) {
      return;
    }
    const item = normalizeItem(value, index, options);
    if (item) {
      options.remaining.count -= 1;
      items.push(item);
    }
  });
  return items;
}

function normalizeItem(
  value: unknown,
  index: number,
  options: {
    depth: number;
    usedSlugs: Set<string>;
    validationErrors: string[];
    remaining: { count: number };
  },
): CatalogItem | null {
  if (!isRecord(value)) {
    options.validationErrors.push(
      `Catalog item ${index + 1} was not an object.`,
    );
    return null;
  }
  const title = nonEmptyString(value.title);
  if (!title) {
    options.validationErrors.push(
      `Catalog item ${index + 1} was missing a title.`,
    );
    return null;
  }
  const children = Array.isArray(value.children)
    ? normalizeItems(value.children, { ...options, depth: options.depth + 1 })
    : [];
  const rawKind = nonEmptyString(value.kind);
  const kind: "page" | "category" =
    rawKind === "category" || (!nonEmptyString(value.path) && children.length)
      ? "category"
      : "page";
  const slug = uniqueSlug(
    nonEmptyString(value.slug) ?? title,
    options.usedSlugs,
  );
  const path = nonEmptyString(value.path) ?? null;
  return {
    title: title.slice(0, 120),
    slug,
    path,
    order: integerValue(value.order) ?? index,
    kind,
    topic: nonEmptyString(value.topic) ?? "",
    source_hints: stringList(value.source_hints).slice(0, 12),
    ...(children.length ? { children } : {}),
  };
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
  validationErrors.push("LLM catalog response was not valid JSON.");
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

function uniqueSlug(value: string, used: Set<string>): string {
  const base = slugify(value);
  let candidate = base;
  let suffix = 2;
  while (used.has(candidate)) {
    candidate = `${base}-${suffix}`;
    suffix += 1;
  }
  used.add(candidate);
  return candidate;
}

function nonEmptyString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function stringValue(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function numberValue(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function integerValue(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) ? value : null;
}

function stringList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
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

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
