import type { CodeWikiStoreApi } from "../db/types.js";
import { notFoundError } from "../errors.js";
import {
  LlmCallError,
  type CachedLlmCompletion,
  type LlmOperation,
} from "../llm/cache.js";
import type {
  CodeGraphNode,
  DocCatalog,
  GraphCommunity,
  JsonObject,
  RepoDescriptor,
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
  communities: GraphCommunity[];
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
      const completion = await this.llm.complete(request.repoId, {
        taskType: "catalog",
        cacheKey: `wiki-catalog:${request.languageCode}`,
        modelAlias: "catalog",
        promptVersion: "ts-wiki-catalog-v1",
        inputPayload: llmInputPayload(context),
        messages: wikiCatalogMessages(context),
        completion: { responseFormat: "json_object" },
      });
      const normalized = normalizeCatalogCompletion(
        completion.result.content,
        localDraft,
      );
      if (!normalized.items.length) {
        return {
          catalog: await this.saveCatalog(context, () => localDraft),
          validation_errors: normalized.validationErrors,
          llm: {
            status: "fallback",
            error: normalized.validationErrors.join("; ") || "Empty catalog.",
            run_id: completion.run.id,
          },
        };
      }
      return {
        catalog: await this.saveCatalog(context, () => normalized),
        validation_errors: normalized.validationErrors,
        llm: llmMetadata("success", completion),
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
    return {
      repo,
      request,
      nodes: graph.nodes,
      communities: await this.store.listGraphCommunities(request.repoId),
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
  context: WikiCatalogContext,
): LlmOperation["messages"] {
  return [
    {
      role: "system",
      content: [
        "You design concise source-grounded wiki catalogs for a code repository.",
        'Return only JSON with shape {"title": string, "items": CatalogItem[]}.',
        "CatalogItem fields: title, slug, kind, path, order, topic, source_hints, children.",
        'Use kind "category" for groups and "page" for pages.',
        "Use existing repository paths in path/source_hints when possible.",
      ].join(" "),
    },
    {
      role: "user",
      content: `Catalog request:\n${JSON.stringify(llmInputPayload(context))}`,
    },
  ];
}

function llmInputPayload(context: WikiCatalogContext): JsonObject {
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
    repo_name: context.repo.name,
    language_code: context.request.languageCode,
    local_title: catalogTitle(context.repo.name),
    local_items: context.localItems,
    files,
    symbols,
    communities: context.communities.slice(0, 40).map((community) => ({
      id: community.id,
      name: community.name,
      level: community.level,
      rank: community.rank,
      summary: community.summary,
    })),
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
