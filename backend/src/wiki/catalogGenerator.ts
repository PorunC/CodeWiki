import {
  readdirSync,
  readFileSync,
  statSync,
  type Dirent,
  type Stats,
} from "node:fs";
import { basename, relative, resolve } from "node:path";
import type { CodeWikiStoreApi } from "../db/types.js";
import { notFoundError } from "../errors.js";
import { buildRetrievalTrace } from "../graphrag/retrieval.js";
import {
  LlmCallError,
  type CachedLlmCompletion,
  type LlmOperation,
} from "../llm/cache.js";
import { filterWikiGraph } from "../services/fileRoles.js";
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

const CATALOG_GENERATION_ATTEMPTS = 3;
const CATALOG_RETRIEVAL_LIMIT = 18;
const CATALOG_PROMPT_VERSION = "catalog:deepwiki:v4";
const MAX_REPOSITORY_TREE_DEPTH = 3;
const MAX_REPOSITORY_TREE_ENTRIES_PER_DIR = 80;
const MAX_README_CHARS = 6000;

const README_NAMES = [
  "README.md",
  "README.MD",
  "readme.md",
  "README.rst",
  "README.txt",
  "README",
];

const COMMON_KEY_FILES = [
  "README.md",
  "pyproject.toml",
  "package.json",
  "tsconfig.json",
  "vite.config.ts",
  "next.config.ts",
  "requirements.txt",
  "Dockerfile",
  "docker-compose.yml",
  "compose.yaml",
  "Makefile",
  ".env.example",
];

const EXCLUDED_CONTEXT_DIRS = new Set([
  ".git",
  ".hg",
  ".svn",
  ".idea",
  ".vscode",
  "__pycache__",
  ".pytest_cache",
  ".ruff_cache",
  ".mypy_cache",
  ".venv",
  "venv",
  "node_modules",
  "dist",
  "build",
  "coverage",
  ".next",
  ".nuxt",
  ".turbo",
  "target",
  "out",
  ".output",
]);

const SPECIAL_CATALOG_PAGES: readonly CatalogItem[] = [
  {
    title: "Overview",
    slug: "overview",
    path: "overview",
    order: 0,
    kind: "page",
    topic:
      "repository overview, entry points, README, and main developer orientation",
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
      "repository architecture, runtime layers, core components, and cross-module flows",
    source_hints: [],
    children: [],
  },
  {
    title: "Reading Guide",
    slug: "reading-guide",
    path: "reading-guide",
    order: 2,
    kind: "page",
    topic:
      "recommended reading order for understanding the repository from entry points to internals",
    source_hints: ["README.md"],
    children: [],
  },
  {
    title: "Dependencies",
    slug: "dependencies",
    path: "dependencies",
    order: 3,
    kind: "page",
    topic:
      "internal dependencies, external packages, imports, configuration, and integration boundaries",
    source_hints: [],
    children: [],
  },
];

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
    target_depth:
      "1-2 levels; avoid drill-down pages unless evidence is strong",
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
    target_depth:
      "2 levels for most areas; use 3 only for clear subsystem boundaries",
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
      "16-32 focused pages; use fewer only when the evidence is genuinely small, and more when distinct subsystems are visible",
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
    target_depth:
      "2-3 levels; use 4 only for large, strongly evidenced subsystems",
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
      "3 levels for complex areas; use 4 only where the graph shows clear boundaries",
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
      for (
        let attempt = 0;
        attempt < CATALOG_GENERATION_ATTEMPTS;
        attempt += 1
      ) {
        completion = await this.llm.complete(request.repoId, {
          taskType: "catalog",
          cacheKey: `catalog:v4:${context.retrievalTrace.trace_id}:attempt:${attempt + 1}`,
          modelAlias: "catalog",
          promptVersion: CATALOG_PROMPT_VERSION,
          inputPayload: attemptPayload,
          messages: wikiCatalogMessages(attemptPayload, validationErrors),
          completion: { responseFormat: "json_object" },
        });
        const normalized = normalizeCatalogCompletion(
          completion.result.content,
          localDraft,
          catalogScale(context),
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
    const wikiGraph = filterWikiGraph(graph.nodes, graph.edges);
    const retrievalTrace = await this.store.saveRetrievalTrace(
      await buildRetrievalTrace(
        this.store,
        request.repoId,
        "repository overview",
        {
          maxHops: 3,
          limit: CATALOG_RETRIEVAL_LIMIT,
        },
      ),
    );
    const chunks = await this.store.listCodeChunks(request.repoId);
    return {
      repo,
      request,
      nodes: wikiGraph.nodes,
      edges: wikiGraph.edges,
      chunks,
      communities: await this.store.listGraphCommunities(request.repoId),
      retrievalTrace,
      localItems: buildCatalogItems(wikiGraph.nodes),
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
  let instruction =
    "Return only a valid JSON object. The object must contain `title` and `items`; `items` must be an array of catalog items. Do not include Markdown fences, comments, trailing commas, or prose outside JSON.";
  if (validationErrors.length) {
    instruction = `${instruction}\nRepair the previous response. Validation errors: ${JSON.stringify(validationErrors)}`;
  }
  return [
    {
      role: "system",
      content: catalogSystemPrompt(),
    },
    {
      role: "user",
      content: stableJsonMessage("Stable catalog generation contract", {
        instructions: instruction,
      }),
    },
    {
      role: "user",
      content: dynamicJsonMessage("Catalog payload", payload),
    },
  ];
}

function llmInputPayload(context: WikiCatalogContext): JsonObject {
  const scale = catalogScale(context);
  return {
    repo: {
      id: context.repo.id,
      name: context.repo.name,
      path: context.repo.path,
      git_url: context.repo.git_url,
      commit_hash: context.repo.commit_hash,
    },
    language_code: context.request.languageCode,
    documentation_style: {
      name: "DeepWiki",
      shape:
        "hierarchical developer wiki with Overview first, subsystem pages, workflow drill-downs, and source-grounded topics",
      audiences: [
        "new developers who need orientation and getting-started guidance",
        "users who need how-to-use pages for API or UI surfaces",
        "contributors who need architecture and developer guide pages",
        "operators who need configuration, deployment, and operations pages when evidenced",
      ],
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
        "split broad modules into child pages by workflow, API surface, data contract, UI surface, provider, or operational concern",
        "avoid file-by-file catalogs unless a file is the public surface",
        "exclude tests/docs/generated output from core feature pages unless explicitly scoped",
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
    community_hierarchy: communityHierarchy(
      context.retrievalTrace.community_summaries,
    ),
    source_chunks: sourceChunkSummaries(context.retrievalTrace.source_chunks),
    required_json_shape: {
      title: "Code Wiki",
      items: catalogRequiredJsonShapeItems(),
    },
  };
}

function catalogRequiredJsonShapeItems(): CatalogItem[] {
  return [
    ...SPECIAL_CATALOG_PAGES.map((item) => ({ ...item })),
    {
      title: "Backend Services",
      slug: "backend-services",
      path: "backend-services",
      order: 4,
      kind: "category",
      topic:
        "backend service layer, API routes, storage, and background workflows",
      source_hints: [],
      children: [
        {
          title: "API Routes",
          slug: "api-routes",
          path: "backend-services/api-routes",
          order: 0,
          kind: "page",
          topic:
            "FastAPI route modules, request payloads, response payloads, and service boundaries",
          source_hints: ["backend/app/api"],
          children: [],
        },
        {
          title: "Wiki Generation",
          slug: "wiki-generation",
          path: "backend-services/wiki-generation",
          order: 1,
          kind: "category",
          topic:
            "catalog generation, page generation, translation, sources, and diagrams",
          source_hints: ["backend/app/services/wiki"],
          children: [
            {
              title: "Catalog Planning",
              slug: "catalog-planning",
              path: "backend-services/wiki-generation/catalog-planning",
              order: 0,
              kind: "page",
              topic:
                "wiki catalog generation, hierarchy planning, source hints, and module candidates",
              source_hints: ["backend/app/services/wiki/catalog_generator.py"],
              children: [],
            },
          ],
        },
      ],
    },
  ];
}

function normalizeCatalogCompletion(
  content: string,
  fallback: CatalogDraft,
  scale: CatalogScale,
): NormalizedCatalog {
  const validationErrors: string[] = [];
  const parsed = parseJsonObject(content, validationErrors);
  if (!parsed) {
    return { ...fallback, items: [], validationErrors };
  }
  const root = catalogRoot(parsed);
  const rawItems =
    Array.isArray(root.items) && root.items.length
      ? root.items
      : Array.isArray(root.pages)
        ? root.pages
        : root.items;
  if (!Array.isArray(rawItems)) {
    validationErrors.push("Catalog response must contain an items array.");
    return { ...fallback, items: [], validationErrors };
  }
  const topLevelLimit = Math.max(
    SPECIAL_CATALOG_PAGES.length,
    scale.max_top_level_items,
  );
  const totalItemLimit = Math.max(
    SPECIAL_CATALOG_PAGES.length,
    scale.max_total_items,
  );
  const usedSlugs = new Set<string>();
  const items = limitCatalogItems(
    sortCatalogItems(
      ensureSpecialCatalogPages(
        normalizeItems(rawItems.slice(0, topLevelLimit), {
          depth: 0,
          usedSlugs,
          validationErrors,
          maxDepth: scale.max_depth,
          maxChildrenPerItem: scale.max_children_per_item,
        }),
      ),
    ).slice(0, topLevelLimit),
    totalItemLimit,
  );
  const title = nonEmptyString(root.title) ?? fallback.title;
  return { title, items, validationErrors };
}

function catalogRoot(parsed: JsonObject): JsonObject {
  return isRecord(parsed.catalog) ? parsed.catalog : parsed;
}

function ensureSpecialCatalogPages(items: CatalogItem[]): CatalogItem[] {
  const existingSlugs = new Set(
    flattenCatalogItems(items).map((item) => item.slug),
  );
  const nextItems = [...items];
  for (const special of SPECIAL_CATALOG_PAGES) {
    if (special.slug && existingSlugs.has(special.slug)) {
      continue;
    }
    nextItems.push({ ...special, children: [] });
    if (special.slug) {
      existingSlugs.add(special.slug);
    }
  }
  return nextItems.map((item) => {
    const special = SPECIAL_CATALOG_PAGES.find(
      (page) => page.slug === item.slug,
    );
    return {
      ...item,
      order: special?.order ?? (item.order ?? 0) + SPECIAL_CATALOG_PAGES.length,
    };
  });
}

function flattenCatalogItems(items: CatalogItem[]): CatalogItem[] {
  const flattened: CatalogItem[] = [];
  for (const item of items) {
    flattened.push(item);
    if (Array.isArray(item.children)) {
      flattened.push(...flattenCatalogItems(item.children));
    }
  }
  return flattened;
}

function sortCatalogItems(items: CatalogItem[]): CatalogItem[] {
  return [...items]
    .map((item) => {
      const sorted: CatalogItem = { ...item };
      if (Array.isArray(item.children)) {
        sorted.children = sortCatalogItems(item.children);
      }
      return sorted;
    })
    .sort(
      (left, right) =>
        (left.order ?? 0) - (right.order ?? 0) ||
        (left.title ?? "").localeCompare(right.title ?? ""),
    );
}

function limitCatalogItems(
  items: CatalogItem[],
  maxTotalItems: number,
): CatalogItem[] {
  const limited: CatalogItem[] = [];
  let remaining = maxTotalItems;
  for (const item of items) {
    if (remaining <= 0) {
      break;
    }
    const next = catalogItemWithBudget(item, remaining);
    if (!next.item) {
      break;
    }
    limited.push(next.item);
    remaining -= next.used;
  }
  return limited;
}

function catalogItemWithBudget(
  item: CatalogItem,
  budget: number,
): { item: CatalogItem | null; used: number } {
  if (budget <= 0) {
    return { item: null, used: 0 };
  }
  const nextItem: CatalogItem = { ...item, children: [] };
  let used = 1;
  let remaining = budget - 1;
  for (const child of Array.isArray(item.children) ? item.children : []) {
    if (remaining <= 0) {
      break;
    }
    const nextChild = catalogItemWithBudget(child, remaining);
    if (!nextChild.item) {
      break;
    }
    nextItem.children?.push(nextChild.item);
    used += nextChild.used;
    remaining -= nextChild.used;
  }
  return { item: nextItem, used };
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
    "You are generating a DeepWiki-style Code Wiki catalog from a repository graph and",
    "repository context.",
    "",
    "Analysis workflow:",
    "- First read the repository README, entry points, compact directory tree, and graph",
    "  evidence in the payload before deciding pages.",
    "- Treat the directory tree and graph as a module map. Group related files, symbols,",
    "  routes, models, and workflows into logical developer-facing modules.",
    "- Identify the main systems, capabilities, workflows, public surfaces, data contracts,",
    "  and UI or API areas. Use individual files only as evidence for those boundaries.",
    "- Cross-check each proposed page against source_hints, graph nodes, source chunks,",
    "  entry points, or README claims.",
    "- If a topic is only weakly evidenced, merge it into a broader page instead of",
    "  creating a thin page.",
    "- Prefer a leaf-first mindset: child pages carry implementation detail, while parent",
    "  categories or parent pages summarize how those children fit together. When a parent",
    "  would otherwise cover many unrelated responsibilities, split it into children.",
    "",
    "Organization goals:",
    "- Build a navigable documentation tree, not a flat list of summaries.",
    '- Consider audience explicitly: new developers need "Getting Started" or a quick',
    '  orientation, users need a "User Guide" or "How to Use" section, contributors need',
    '  "Architecture" and "Developer Guide" sections, and operators need "Configuration",',
    '  "Deployment", or "Operations" only when those concerns are evidenced.',
    "- Prefer a DeepWiki-like progression when evidence supports it: Overview, Architecture,",
    "  Reading Guide, Dependencies, Getting Started/User Guide, Core Workflows, API",
    "  Reference, Developer Guide, and Operations.",
    '- Include at least one "how to use" section and one "how it works" section when the',
    "  repository has both API or UI surfaces and internal implementation layers.",
    '- Start with top-level "Overview", "Architecture", "Reading Guide", and',
    '  "Dependencies" pages, then group pages by real systems, layers, workflows, data',
    "  models, APIs, services, and frontend surfaces that appear in the provided graph.",
    "- Use the top-level section, total page, and depth ranges from `granularity_contract`.",
    "  Use children aggressively when a subsystem has enough retrieved evidence to justify",
    "  drill-down pages.",
    "- A parent can contain category children when a layer has several distinct workflows",
    "  or surfaces, but do not exceed the configured `catalog_scale.hard_limits.max_depth`.",
    "- Follow the `catalog_scale` and `granularity_contract` values in the payload. Treat",
    "  `catalog_scale.hard_limits.max_total_items` as the maximum total catalog items,",
    "  counting both pages and categories.",
    '- Use `kind: "category"` for parent section pages that should receive lightweight',
    '  overview content and point readers to child pages. Use `kind: "page"` for focused',
    "  documents that carry implementation detail.",
    "- Prefer detailed content for leaf pages. Parent category pages should summarize the",
    "  child section, explain the mental model, and avoid repeating child implementation",
    "  details.",
    "- Leaf pages should be narrow enough that `source_hints` are focused. A leaf should",
    "  normally cover one workflow stage, route/API group, data model family, UI view,",
    "  provider integration, export format, CLI/automation flow, or extension point.",
    '- Page titles should be short and concrete, like "Architecture", "Wiki Generation",',
    '  "GraphRAG Retrieval", or "Frontend Wiki View".',
    "- Each topic must be a retrieval query that names the concrete subsystem and key files,",
    "  symbols, or workflows it should cover.",
    "- Include `source_hints` with the most relevant file paths when known.",
    "- Use README and the compact directory tree to infer documentation boundaries, but keep",
    "  every page grounded in graph nodes, edges, source chunks, or visible repository files.",
    "- Mirror DeepWiki's shape: broad overview first, architecture/system pages next,",
    "  then user-facing workflows, implementation areas, API references, developer",
    "  extension points, and operational topics with focused child pages.",
    '- Parent categories should have concise, meaningful names such as "Backend Services",',
    '  "Graph Pipeline", "Wiki Generation", "Frontend", or "Operations" only when those',
    "  boundaries are evident in the repository.",
    '- Split broad categories into concrete children. For example, "Backend Services" can',
    '  have "API Routes", "Graph Analysis", "GraphRAG Retrieval", "Wiki Generation",',
    '  "Persistence", and "Incremental Updates" when those boundaries are evidenced.',
    '  "Frontend" can have "Graph Explorer", "Wiki Reader", "Ask Interface", "Exports",',
    '  and "Settings" when evidenced.',
    "- Prefer pages such as Overview, Architecture, Core Workflows, API Surface,",
    "  Data Model, Configuration, Frontend/UI, Testing, and Operations only when those",
    "  topics are actually present in the repository evidence.",
    "- Keep child paths stable and URL-friendly. Use child pages for meaningful drill-downs,",
    "  not for every source file.",
    "- Exclude tests, docs, examples, generated output, and scaffolding from core feature",
    "  pages unless the page is explicitly about testing, documentation, examples, or",
    "  operations.",
    "",
    "Coverage checklist:",
    "- Include the application bootstrap or runtime entry points when present.",
    "- Include public API or UI surfaces when present.",
    "- Include data persistence, schemas, migrations, or storage models when present.",
    "- Include core pipelines, background jobs, indexing, retrieval, generation, or",
    "  rendering workflows when present.",
    "- Include configuration, environment variables, deployment, or operational concerns",
    "  only when evidenced by repository files.",
    "- If a complex subsystem has several strongly related files, create one detailed page",
    "  for the subsystem instead of one page per file.",
    "- If a complex subsystem has several distinct responsibilities, create a category",
    "  plus multiple focused leaf pages rather than one broad implementation page.",
    "- Use `module_candidates` as a shortlist of directories and symbol clusters that",
    "  deserve detailed splitting. Large candidates should normally become categories or",
    "  multiple leaf pages unless the evidence shows they are trivial.",
    "",
    "Rules:",
    "- Use only the provided graph context, community summaries, nodes, edges, and source",
    "  references.",
    "- Do not invent modules, APIs, files, dependencies, or deployment surfaces.",
    "- Return a concise hierarchy suitable for a developer-facing wiki.",
    "- Return only JSON in the requested shape.",
    "- Do not create pages for individual helpers, single tests, or isolated classes unless",
    "  they are the primary public surface of the repository.",
    "- Do not collapse API, storage, background jobs, rendering, exports, and configuration",
    "  into one page when source evidence shows they are separate concerns.",
    "",
    "Catalog item shape:",
    "- `title`: display name.",
    "- `slug`: URL-safe stable id.",
    "- `path`: URL-safe path, usually same as slug.",
    "- `order`: integer ordering inside its parent.",
    '- `kind`: `"page"` or `"category"`.',
    "- `topic`: retrieval query for this page. Name the concrete subsystem, workflow,",
    "  files, symbols, endpoints, models, and configuration keys that should be retrieved.",
    "- `source_hints`: array of relevant file paths. Include the most important P0/P1",
    "  files for the page: primary implementation, public contracts, routes, models,",
    "  configuration, and representative tests when they clarify behavior.",
    "- `children`: nested catalog items.",
  ].join("\n");
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
  return repositoryFilesystemContext(context.repo.path);
}

function repositoryFilesystemContext(repoPath: string): JsonObject {
  const root = resolve(repoPath);
  return {
    project_type: detectProjectType(root),
    directory_tree_format: "compact",
    directory_tree: directoryTree(root),
    readme_content: readmeContent(root),
    key_files: keyFiles(root),
    entry_points: entryPoints(root),
  };
}

function directoryTree(root: string): string {
  if (!safeStat(root)?.isDirectory()) {
    return basename(root);
  }
  const lines = [basename(root)];
  appendTree(root, lines, 0);
  return lines.join("\n");
}

function appendTree(directory: string, lines: string[], depth: number): void {
  if (depth >= MAX_REPOSITORY_TREE_DEPTH) {
    return;
  }
  const entries = safeReadDir(directory)
    .filter(
      (entry) =>
        !entry.name.startsWith(".") && !EXCLUDED_CONTEXT_DIRS.has(entry.name),
    )
    .sort((left, right) => {
      const leftIsFile = left.isFile();
      const rightIsFile = right.isFile();
      return (
        Number(leftIsFile) - Number(rightIsFile) ||
        left.name.toLowerCase().localeCompare(right.name.toLowerCase())
      );
    })
    .slice(0, MAX_REPOSITORY_TREE_ENTRIES_PER_DIR);
  for (const entry of entries) {
    const absolutePath = resolve(directory, entry.name);
    const suffix = entry.isDirectory() ? "/" : "";
    lines.push(`${"  ".repeat(depth + 1)}- ${entry.name}${suffix}`);
    if (entry.isDirectory()) {
      appendTree(absolutePath, lines, depth + 1);
    }
  }
}

function readmeContent(root: string): string {
  for (const name of README_NAMES) {
    const path = resolve(root, name);
    if (!safeStat(path)?.isFile()) {
      continue;
    }
    const content = safeReadFile(path).trim();
    return content.length > MAX_README_CHARS
      ? `${content.slice(0, MAX_README_CHARS).trimEnd()}\n\n[README truncated]`
      : content;
  }
  return "";
}

function keyFiles(root: string): string[] {
  const paths = COMMON_KEY_FILES.filter((name) =>
    safeStat(resolve(root, name))?.isFile(),
  );
  paths.push(
    ...safeReadDir(root)
      .filter(
        (entry) =>
          entry.isFile() &&
          (entry.name.endsWith(".sln") || entry.name.endsWith(".csproj")),
      )
      .map((entry) => entry.name),
  );
  return uniqueStrings(paths).sort((left, right) => left.localeCompare(right));
}

function entryPoints(root: string): string[] {
  const directPatterns = [
    "backend/app/main.py",
    "app.py",
    "main.py",
    "__main__.py",
    "manage.py",
    "frontend/src/main.tsx",
    "frontend/src/main.ts",
    "src/main.tsx",
    "src/main.ts",
    "src/App.tsx",
    "src/App.vue",
    "Program.cs",
    "Startup.cs",
  ].filter((filePath) => safeStat(resolve(root, filePath))?.isFile());
  const goCommandEntries = safeReadDir(resolve(root, "cmd")).flatMap(
    (entry) => {
      if (!entry.isDirectory()) {
        return [];
      }
      const filePath = `cmd/${entry.name}/main.go`;
      return safeStat(resolve(root, filePath))?.isFile() ? [filePath] : [];
    },
  );
  return uniqueStrings([...directPatterns, ...goCommandEntries])
    .sort((left, right) => left.localeCompare(right))
    .slice(0, 12);
}

function detectProjectType(root: string): string {
  const types: string[] = [];
  if (
    safeStat(resolve(root, "pyproject.toml"))?.isFile() ||
    safeStat(resolve(root, "requirements.txt"))?.isFile()
  ) {
    types.push("python");
  }
  const packageTexts = packageJsonFiles(root)
    .slice(0, 5)
    .map((filePath) => safeReadFile(resolve(root, filePath)))
    .filter(Boolean);
  if (packageTexts.length) {
    const packageText = packageTexts.join("\n");
    types.push(
      /"(react|next|vite|vue|angular)"/.test(packageText)
        ? "frontend"
        : "nodejs",
    );
  }
  if (
    safeReadDir(root).some(
      (entry) => entry.name.endsWith(".sln") || entry.name.endsWith(".csproj"),
    )
  ) {
    types.push("dotnet");
  }
  if (safeStat(resolve(root, "go.mod"))?.isFile()) {
    types.push("go");
  }
  if (safeStat(resolve(root, "Cargo.toml"))?.isFile()) {
    types.push("rust");
  }
  if (
    safeStat(resolve(root, "pom.xml"))?.isFile() ||
    safeReadDir(root).some((entry) => entry.name.startsWith("build.gradle"))
  ) {
    types.push("java");
  }
  if (!types.length) {
    return "unknown";
  }
  return types.length > 1
    ? `fullstack:${types.join("+")}`
    : (types[0] ?? "unknown");
}

function safeReadDir(path: string): Dirent[] {
  try {
    return readdirSync(path, { withFileTypes: true });
  } catch {
    return [];
  }
}

function safeReadFile(path: string): string {
  try {
    return readFileSync(path, "utf8");
  } catch {
    return "";
  }
}

function safeStat(path: string): Stats | null {
  try {
    return statSync(path);
  } catch {
    return null;
  }
}

function packageJsonFiles(root: string): string[] {
  const results: string[] = [];
  const visit = (directory: string, depth: number) => {
    if (results.length >= 5 || depth > MAX_REPOSITORY_TREE_DEPTH + 2) {
      return;
    }
    for (const entry of safeReadDir(directory)) {
      if (entry.name.startsWith(".") || EXCLUDED_CONTEXT_DIRS.has(entry.name)) {
        continue;
      }
      const absolutePath = resolve(directory, entry.name);
      const relativePath = relative(root, absolutePath).replace(/\\/g, "/");
      if (entry.isFile() && entry.name === "package.json") {
        results.push(relativePath);
      } else if (entry.isDirectory()) {
        visit(absolutePath, depth + 1);
      }
      if (results.length >= 5) {
        return;
      }
    }
  };
  visit(root, 0);
  return results;
}

function fileCountForNodes(nodes: CodeGraphNode[]): number {
  const filePaths = uniqueStrings(
    nodes
      .filter(
        (node) =>
          Boolean(node.file_path) &&
          !["directory", "module", "repository"].includes(node.type),
      )
      .map((node) => node.file_path),
  );
  return (
    filePaths.length || nodes.filter((node) => node.type === "file").length
  );
}

function bucket(value: number, thresholds: number[]): number {
  const index = thresholds.findIndex((threshold) => value <= threshold);
  return index === -1 ? thresholds.length : index;
}

function modulePathForFile(filePath: string): string {
  const parts = filePath.split("/").filter(Boolean);
  if (parts.length <= 1) {
    return ".";
  }
  const directoryParts = parts.slice(0, -1);
  if (!directoryParts.length) {
    return ".";
  }
  if (
    (directoryParts[0] === "backend" || directoryParts[0] === "frontend") &&
    directoryParts.length >= 3
  ) {
    return directoryParts.slice(0, 4).join("/");
  }
  return directoryParts.slice(0, 3).join("/");
}

function increment(values: Map<string, number>, key: string): void {
  values.set(key, (values.get(key) ?? 0) + 1);
}

function topEntries(values: Map<string, number>, limit: number): JsonObject {
  const entries = [...values.entries()]
    .sort(
      (left, right) => right[1] - left[1] || left[0].localeCompare(right[0]),
    )
    .slice(0, limit);
  return Object.fromEntries(entries);
}

function splitHint(
  modulePath: string,
  files: string[],
  nodeTypes: Map<string, number>,
): string {
  const names = new Set(
    files.map((filePath) => basename(filePath).toLowerCase()),
  );
  if (
    files.some(
      (filePath) => filePath.includes("api") || filePath.includes("routes"),
    )
  ) {
    return "Consider separate pages for public routes, request/response contracts, and service delegation.";
  }
  if (
    ["models.py", "schema.py", "schemas.py", "database.py"].some((name) =>
      names.has(name),
    )
  ) {
    return "Consider separate pages for data models, repositories, persistence, and migrations.";
  }
  if (
    [...nodeTypes.keys()].some(
      (nodeType) => nodeType.includes("component") || nodeType === "hook",
    )
  ) {
    return "Consider separate pages for UI views, reusable components, hooks, and user workflows.";
  }
  if (files.length >= 6) {
    return `Large module ${modulePath}; split by workflow stage, public surface, and extension point.`;
  }
  if (files.length >= 3) {
    return `Medium module ${modulePath}; use at least one focused implementation leaf page.`;
  }
  return `Small module ${modulePath}; merge into a nearby broader page unless it is a public surface.`;
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
    const group = groups.get(modulePath) ?? {
      files: new Set<string>(),
      nodeTypes: new Map<string, number>(),
      edgeTypes: new Map<string, number>(),
      symbols: [],
    };
    group.files.add(node.file_path);
    increment(group.nodeTypes, node.type);
    if (node.type !== "file" && group.symbols.length < 18) {
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

function sourceChunkSummaries(chunks: JsonObject[]): JsonObject[] {
  return chunks.map((chunk) =>
    compactJsonObject({
      id: chunk.id,
      node_id: chunk.node_id,
      file_path: chunk.file_path,
      start_line: chunk.start_line,
      end_line: chunk.end_line,
      reasons: chunk.reasons,
    }),
  );
}

function communityHierarchy(communities: JsonObject[]): JsonObject[] {
  const byId = new Map<string, JsonObject>();
  const roots: JsonObject[] = [];
  for (const community of communities) {
    const id = stringValue(community.id);
    if (id) {
      byId.set(id, catalogCommunitySummary(community));
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

function catalogCommunitySummary(community: JsonObject): JsonObject {
  const nodeIds = stringList(community.node_ids);
  const matchedNodeIds = stringList(community.matched_node_ids);
  return {
    id: stringValue(community.id),
    name: stringValue(community.name),
    level: numberValue(community.level),
    parent_id: nonEmptyString(community.parent_id),
    summary: stringValue(community.summary),
    node_count: numberValue(community.node_count) || nodeIds.length,
    matched_node_ids: matchedNodeIds.length ? matchedNodeIds : nodeIds,
  };
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

function uniqueStrings(values: string[]): string[] {
  return [...new Set(values.map((value) => value.trim()).filter(Boolean))];
}

function normalizeItems(
  values: unknown[],
  options: {
    depth: number;
    usedSlugs: Set<string>;
    validationErrors: string[];
    maxDepth: number;
    maxChildrenPerItem: number;
  },
): CatalogItem[] {
  if (options.depth >= options.maxDepth) {
    return [];
  }
  const items: CatalogItem[] = [];
  values.forEach((value, index) => {
    const item = normalizeItem(value, index, options);
    if (item) {
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
    maxDepth: number;
    maxChildrenPerItem: number;
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
  const rawChildren = Array.isArray(value.children) ? value.children : [];
  const children =
    rawChildren.length && options.depth < options.maxDepth - 1
      ? normalizeItems(rawChildren.slice(0, options.maxChildrenPerItem), {
          ...options,
          depth: options.depth + 1,
        })
      : [];
  const rawKind = nonEmptyString(value.kind);
  const kind: "page" | "category" =
    rawKind === "category" ? "category" : "page";
  const slug = uniqueSlug(
    nonEmptyString(value.slug) ?? nonEmptyString(value.path) ?? title,
    options.usedSlugs,
  );
  const path = normalizedCatalogPath(value.path) ?? slug;
  return {
    title,
    slug,
    path,
    order: nonNegativeIntegerValue(value.order) ?? options.usedSlugs.size - 1,
    kind,
    topic: scalarString(value.topic) || title,
    source_hints: arrayValue(value.source_hints)
      .slice(0, 8)
      .map((hint) => String(hint)),
    children,
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

function normalizedCatalogPath(value: unknown): string | null {
  const path = scalarString(value)
    .trim()
    .replace(/^\/+|\/+$/g, "");
  return path || null;
}

function scalarString(value: unknown): string {
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return "";
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

function nonNegativeIntegerValue(value: unknown): number | null {
  const integer = integerValue(value);
  return integer !== null && integer >= 0 ? integer : null;
}

function arrayValue(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
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

function compactJsonObject(values: Record<string, unknown>): JsonObject {
  const payload: JsonObject = {};
  for (const [key, value] of Object.entries(values)) {
    if (value !== undefined && isJsonValue(value)) {
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

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
