import type { CodeWikiStoreApi } from "../db/types.js";
import type { CachedLlmCompletion, LlmOperation } from "../llm/cache.js";
import type { DocCatalog, DocPage, JsonObject, LlmRun } from "../types.js";
import {
  catalogItemTitle,
  catalogGenerationNodes,
  catalogGenerationNodesFromStructure,
  childPageRecordsForItem,
  findCatalogGenerationNode,
  type GenerationNode,
} from "./catalog.js";
import { WikiCatalogGenerator } from "./catalogGenerator.js";
import { WikiPageGenerator } from "./pageGenerator.js";
import {
  llmCachePayloadForTasks,
  pageResultPayload,
  type WikiCatalogResult,
  type WikiPageResult,
} from "./payloads.js";
import { copyWikiLanguage } from "./translation.js";

type WikiLlm = {
  isConfigured(taskType: string): boolean;
  complete(
    repoId: string,
    operation: LlmOperation,
  ): Promise<CachedLlmCompletion>;
};

export class WikiService {
  private readonly catalogGenerator: WikiCatalogGenerator;
  private readonly pageGenerator: WikiPageGenerator;

  constructor(
    private readonly store: CodeWikiStoreApi,
    llm?: WikiLlm,
  ) {
    this.catalogGenerator = new WikiCatalogGenerator(store, llm);
    this.pageGenerator = new WikiPageGenerator(store, llm);
  }

  generateCatalog(repoId: string, languageCode = "en"): Promise<DocCatalog> {
    return this.catalogGenerator.generate({
      repoId,
      languageCode,
    });
  }

  async generateCatalogWithLlmFallback(
    repoId: string,
    languageCode = "en",
  ): Promise<WikiCatalogResult> {
    return this.catalogGenerator.generateWithLlmFallback({
      repoId,
      languageCode,
    });
  }

  async generateAllPages(
    repoId: string,
    languageCode = "en",
  ): Promise<WikiPageResult[]> {
    let catalog = await this.store.getLatestDocCatalog(repoId, languageCode);
    if (!catalog) {
      catalog = await this.generateCatalog(repoId, languageCode);
    }
    const nodes = catalogGenerationNodesFromStructure(catalog.structure);
    const results = nodes.length
      ? orderedResults(
          nodes,
          await this.generateNodes(repoId, nodes, languageCode, false),
        )
      : [await this.generateStandaloneOverview(repoId, languageCode, false)];
    await this.store.deleteDocPagesNotIn(
      repoId,
      results.map((result) => result.page.slug),
      languageCode,
    );
    return results;
  }

  async generateAllPagesWithLlmFallback(
    repoId: string,
    languageCode = "en",
  ): Promise<WikiPageResult[]> {
    let catalog = await this.store.getLatestDocCatalog(repoId, languageCode);
    if (!catalog) {
      catalog = (
        await this.generateCatalogWithLlmFallback(repoId, languageCode)
      ).catalog;
    }
    const nodes = catalogGenerationNodesFromStructure(catalog.structure);
    const results = nodes.length
      ? orderedResults(
          nodes,
          await this.generateNodes(repoId, nodes, languageCode, true),
        )
      : [await this.generateStandaloneOverview(repoId, languageCode, true)];
    await this.store.deleteDocPagesNotIn(
      repoId,
      results.map((result) => result.page.slug),
      languageCode,
    );
    return results;
  }

  async regeneratePage(
    repoId: string,
    slug: string,
    languageCode = "en",
  ): Promise<WikiPageResult> {
    const catalog = await this.store.getLatestDocCatalog(repoId, languageCode);
    if (!catalog) {
      throw new Error("Generate a catalog before regenerating pages.");
    }
    const node = findCatalogGenerationNode(catalog.structure, slug);
    if (!node) {
      throw new Error(`Catalog page not found: ${slug}`);
    }
    const pagesBySlug = new Map<string, DocPage>();
    if (node.hasChildren) {
      const childResults = await this.generateNodes(
        repoId,
        catalogGenerationNodes(node.item.children ?? [], {
          parentSlug: node.slug,
          depth: node.depth + 1,
        }),
        languageCode,
        false,
        pagesBySlug,
      );
      for (const result of childResults.values()) {
        pagesBySlug.set(result.page.slug, result.page);
      }
    }
    return {
      page: await this.pageGenerator.generate({
        repoId,
        slug: node.slug,
        languageCode,
        title: catalogItemTitle(node.item),
        path: node.item.path ?? null,
        parentSlug: node.parentSlug,
        childPages: childPageRecordsForItem(node.item, pagesBySlug),
      }),
      validation_errors: [],
    };
  }

  async regeneratePageWithLlmFallback(
    repoId: string,
    slug: string,
    languageCode = "en",
  ): Promise<WikiPageResult> {
    const catalog = await this.store.getLatestDocCatalog(repoId, languageCode);
    if (!catalog) {
      throw new Error("Generate a catalog before regenerating pages.");
    }
    const node = findCatalogGenerationNode(catalog.structure, slug);
    if (!node) {
      throw new Error(`Catalog page not found: ${slug}`);
    }
    const pagesBySlug = new Map<string, DocPage>();
    if (node.hasChildren) {
      const childResults = await this.generateNodes(
        repoId,
        catalogGenerationNodes(node.item.children ?? [], {
          parentSlug: node.slug,
          depth: node.depth + 1,
        }),
        languageCode,
        true,
        pagesBySlug,
      );
      for (const result of childResults.values()) {
        pagesBySlug.set(result.page.slug, result.page);
      }
    }
    return this.pageGenerator.generateWithLlmFallback({
      repoId,
      slug: node.slug,
      languageCode,
      title: catalogItemTitle(node.item),
      path: node.item.path ?? null,
      parentSlug: node.parentSlug,
      childPages: childPageRecordsForItem(node.item, pagesBySlug),
    });
  }

  async updatePages(
    repoId: string,
    languageCode = "en",
    options: { staleSlugs?: string[] } = {},
  ): Promise<JsonObject> {
    let catalog = await this.store.getLatestDocCatalog(repoId, languageCode);
    if (!catalog) {
      catalog = await this.generateCatalog(repoId, languageCode);
    }
    const result = await this.updatePagesForCatalog(
      repoId,
      languageCode,
      catalog,
      false,
      options,
    );
    return this.updatePagesPayload(repoId, languageCode, result);
  }

  async updatePagesWithLlmFallback(
    repoId: string,
    languageCode = "en",
    options: { staleSlugs?: string[] } = {},
  ) {
    let catalog = await this.store.getLatestDocCatalog(repoId, languageCode);
    if (!catalog) {
      catalog = (
        await this.generateCatalogWithLlmFallback(repoId, languageCode)
      ).catalog;
    }
    const result = await this.updatePagesForCatalog(
      repoId,
      languageCode,
      catalog,
      true,
      options,
    );
    return this.updatePagesPayload(repoId, languageCode, result);
  }

  translateWiki(
    repoId: string,
    sourceLanguage = "en",
    targetLanguage: string,
  ): Promise<JsonObject> {
    return copyWikiLanguage(this.store, repoId, sourceLanguage, targetLanguage);
  }

  async llmCachePayload(
    repoId: string,
    taskTypes: string[],
  ): Promise<JsonObject> {
    const runs: LlmRun[] = [];
    for (const taskType of taskTypes) {
      runs.push(
        ...(await Promise.resolve(
          this.store.listLlmRuns(repoId, { taskType }),
        )),
      );
    }
    return llmCachePayloadForTasks((taskType) => {
      if (taskTypes.length === 1) {
        return runs;
      }
      return runs.filter((run) => run.task_type === taskType);
    }, taskTypes);
  }

  private async updatePagesPayload(
    repoId: string,
    languageCode: string,
    update: WikiUpdateResult,
  ): Promise<JsonObject> {
    const hasValidationErrors = update.results.some(
      (result) => result.validation_errors.length > 0,
    );
    return {
      repo_id: repoId,
      language_code: languageCode,
      status: hasValidationErrors
        ? "partial"
        : update.results.length || update.deletedPageCount
          ? "updated"
          : "up_to_date",
      page_count: update.results.length + update.reusedPages.length,
      generated_count: update.results.length,
      reused_count: update.reusedPages.length,
      stale_pages: update.staleSlugs,
      missing_pages: update.missingSlugs,
      metadata_changed_pages: update.metadataChangedSlugs,
      generated_pages: update.results.map((result) => result.page.slug),
      deleted_page_count: update.deletedPageCount,
      pages: update.results.map(pageResultPayload),
      incremental_update: {
        run_id: "",
        status: "not_run",
        affected_files: [],
        changed_files: [],
        new_files: [],
        deleted_files: [],
        stale_pages: [],
        chunk_count: (await this.store.listCodeChunks(repoId)).length,
        errors: [],
      },
      llm_cache: await this.llmCachePayload(repoId, ["catalog", "page"]),
    };
  }

  private async updatePagesForCatalog(
    repoId: string,
    languageCode: string,
    catalog: DocCatalog,
    useLlm: boolean,
    options: { staleSlugs?: string[] } = {},
  ): Promise<WikiUpdateResult> {
    const nodes = catalogGenerationNodesFromStructure(catalog.structure);
    if (!nodes.length) {
      const result = await this.generateStandaloneOverview(
        repoId,
        languageCode,
        useLlm,
      );
      const deletedPageCount = await this.store.deleteDocPagesNotIn(
        repoId,
        [result.page.slug],
        languageCode,
      );
      return {
        results: [result],
        reusedPages: [],
        staleSlugs: [],
        missingSlugs: [result.page.slug],
        metadataChangedSlugs: [],
        deletedPageCount,
      };
    }

    const existingBySlug = new Map(
      (await this.store.listDocPages(repoId, languageCode)).map((page) => [
        page.slug,
        page,
      ]),
    );
    const dirtyPlan = dirtyPagePlan(
      nodes,
      existingBySlug,
      options.staleSlugs ?? [],
    );
    const dirtyNodes = nodes.filter((node) =>
      dirtyPlan.dirtySlugs.has(node.slug),
    );
    const pagesBySlug = new Map(existingBySlug);
    const resultsBySlug = await this.generateNodes(
      repoId,
      dirtyNodes,
      languageCode,
      useLlm,
      pagesBySlug,
    );
    const catalogSlugs = nodes.map((node) => node.slug);
    const deletedPageCount = await this.store.deleteDocPagesNotIn(
      repoId,
      catalogSlugs,
      languageCode,
    );
    const reusedPages = nodes
      .filter(
        (node) =>
          !dirtyPlan.dirtySlugs.has(node.slug) && existingBySlug.has(node.slug),
      )
      .map((node) => existingBySlug.get(node.slug))
      .filter((page): page is DocPage => Boolean(page));

    return {
      results: nodes
        .filter((node) => resultsBySlug.has(node.slug))
        .map((node) => resultsBySlug.get(node.slug))
        .filter((result): result is WikiPageResult => Boolean(result)),
      reusedPages,
      staleSlugs: dirtyPlan.staleSlugs,
      missingSlugs: dirtyPlan.missingSlugs,
      metadataChangedSlugs: dirtyPlan.metadataChangedSlugs,
      deletedPageCount,
    };
  }

  private async generateNodes(
    repoId: string,
    nodes: GenerationNode[],
    languageCode: string,
    useLlm: boolean,
    pagesBySlug: Map<string, DocPage> = new Map(),
  ): Promise<Map<string, WikiPageResult>> {
    const resultsBySlug = new Map<string, WikiPageResult>();
    const leafNodes = nodes.filter((node) => !node.hasChildren);
    for (const node of leafNodes) {
      const result = await this.generateNode(
        repoId,
        node,
        languageCode,
        useLlm,
        [],
      );
      resultsBySlug.set(node.slug, result);
      pagesBySlug.set(node.slug, result.page);
    }

    const parentNodes = nodes
      .filter((node) => node.hasChildren)
      .sort(
        (left, right) => right.depth - left.depth || left.order - right.order,
      );
    for (const node of parentNodes) {
      const result = await this.generateNode(
        repoId,
        node,
        languageCode,
        useLlm,
        childPageRecordsForItem(node.item, pagesBySlug),
      );
      resultsBySlug.set(node.slug, result);
      pagesBySlug.set(node.slug, result.page);
    }
    return resultsBySlug;
  }

  private async generateNode(
    repoId: string,
    node: GenerationNode,
    languageCode: string,
    useLlm: boolean,
    childPages: DocPage[],
  ): Promise<WikiPageResult> {
    const request = {
      repoId,
      slug: node.slug,
      languageCode,
      title: catalogItemTitle(node.item),
      path: node.item.path ?? null,
      parentSlug: node.parentSlug,
      childPages,
    };
    if (useLlm) {
      return this.pageGenerator.generateWithLlmFallback(request);
    }
    return {
      page: await this.pageGenerator.generate(request),
      validation_errors: [],
    };
  }

  private async generateStandaloneOverview(
    repoId: string,
    languageCode: string,
    useLlm: boolean,
  ): Promise<WikiPageResult> {
    const node: GenerationNode = {
      item: {
        title: "Overview",
        slug: "overview",
        path: null,
        order: 0,
        kind: "page",
        topic: "Repository overview",
      },
      parentSlug: null,
      slug: "overview",
      depth: 0,
      order: 0,
      hasChildren: false,
    };
    return this.generateNode(repoId, node, languageCode, useLlm, []);
  }
}

type DirtyPagePlan = {
  dirtySlugs: Set<string>;
  staleSlugs: string[];
  missingSlugs: string[];
  metadataChangedSlugs: string[];
};

type WikiUpdateResult = {
  results: WikiPageResult[];
  reusedPages: DocPage[];
  staleSlugs: string[];
  missingSlugs: string[];
  metadataChangedSlugs: string[];
  deletedPageCount: number;
};

function dirtyPagePlan(
  nodes: GenerationNode[],
  existingBySlug: Map<string, DocPage>,
  forcedStaleSlugs: string[] = [],
): DirtyPagePlan {
  const dirtySlugs = new Set<string>();
  const staleSlugs: string[] = [];
  const missingSlugs: string[] = [];
  const metadataChangedSlugs: string[] = [];
  const parentBySlug = new Map(
    nodes.map((node) => [node.slug, node.parentSlug]),
  );
  const forcedStale = new Set(forcedStaleSlugs);

  for (const node of nodes) {
    const existing = existingBySlug.get(node.slug);
    if (!existing) {
      missingSlugs.push(node.slug);
      dirtySlugs.add(node.slug);
      continue;
    }
    if (existing.status !== "generated" || forcedStale.has(node.slug)) {
      staleSlugs.push(node.slug);
      dirtySlugs.add(node.slug);
      continue;
    }
    const expectedTitle = node.item.title || "";
    if (
      (expectedTitle && existing.title !== expectedTitle) ||
      existing.parent_slug !== node.parentSlug
    ) {
      metadataChangedSlugs.push(node.slug);
      dirtySlugs.add(node.slug);
    }
  }

  for (const slug of [
    ...missingSlugs,
    ...staleSlugs,
    ...metadataChangedSlugs,
  ]) {
    let parentSlug = parentBySlug.get(slug) ?? null;
    while (parentSlug) {
      dirtySlugs.add(parentSlug);
      parentSlug = parentBySlug.get(parentSlug) ?? null;
    }
  }

  return {
    dirtySlugs,
    staleSlugs: unique(staleSlugs),
    missingSlugs: unique(missingSlugs),
    metadataChangedSlugs: unique(metadataChangedSlugs),
  };
}

function unique(values: string[]): string[] {
  return [...new Set(values)];
}

function orderedResults(
  nodes: GenerationNode[],
  resultsBySlug: Map<string, WikiPageResult>,
): WikiPageResult[] {
  return nodes
    .map((node) => resultsBySlug.get(node.slug))
    .filter((result): result is WikiPageResult => Boolean(result));
}
