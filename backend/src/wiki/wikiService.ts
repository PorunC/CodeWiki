import { randomUUID } from "node:crypto";
import type { CodeWikiStoreApi } from "../db/types.js";
import { GraphRAGService } from "../graphrag/graphragService.js";
import { retrievalTracePayload } from "../graphrag/payloads.js";
import type { CachedLlmCompletion, LlmOperation } from "../llm/cache.js";
import type {
  DocCatalog,
  DocPage,
  JsonObject,
  JsonValue,
  LlmRun,
  RetrievalTrace,
} from "../types.js";
import {
  catalogItemTitle,
  catalogGenerationNodes,
  catalogGenerationNodesFromStructure,
  childPageRecordsForItem,
  findCatalogGenerationNode,
  type CatalogItem,
  type GenerationNode,
} from "./catalog.js";
import { WikiCatalogGenerator } from "./catalogGenerator.js";
import { WikiPageGenerator } from "./pageGenerator.js";
import {
  catalogPayload,
  llmCachePayloadForTasks,
  pagePayload,
  pageResultPayload,
  type WikiCatalogResult,
  type WikiPageResult,
} from "./payloads.js";
import { translateWikiLanguage } from "./translation.js";

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
  private readonly llm: WikiLlm | undefined;

  constructor(
    private readonly store: CodeWikiStoreApi,
    llm?: WikiLlm,
    private readonly graphRag: GraphRAGService = new GraphRAGService(store),
  ) {
    this.llm = llm;
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
    const language = normalizeLanguage(languageCode);
    if (!isBaseLanguage(language)) {
      await this.ensureBaseCatalogWithLlmFallback(repoId);
      await this.translateWiki(repoId, BASE_WIKI_LANGUAGE, language);
      const catalog = await this.store.getLatestDocCatalog(repoId, language);
      if (!catalog) {
        throw new Error(
          `Translated catalog not found for language: ${language}`,
        );
      }
      return { catalog, validation_errors: [] };
    }
    return this.catalogGenerator.generateWithLlmFallback({
      repoId,
      languageCode: language,
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
    const language = normalizeLanguage(languageCode);
    if (!isBaseLanguage(language)) {
      await this.ensureBasePagesWithLlmFallback(repoId);
      await this.translateWiki(repoId, BASE_WIKI_LANGUAGE, language);
      return this.translatedPageResults(repoId, language);
    }
    let catalog = await this.store.getLatestDocCatalog(repoId, language);
    if (!catalog) {
      catalog = (await this.generateCatalogWithLlmFallback(repoId, language))
        .catalog;
    }
    const nodes = catalogGenerationNodesFromStructure(catalog.structure);
    const results = nodes.length
      ? orderedResults(
          nodes,
          await this.generateNodes(repoId, nodes, language, true),
        )
      : [await this.generateStandaloneOverview(repoId, language, true)];
    await this.store.deleteDocPagesNotIn(
      repoId,
      results.map((result) => result.page.slug),
      language,
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
        kind: node.item.kind ?? "page",
        path: node.item.path ?? null,
        topic: wikiPageTopic(node.item),
        sourceHints: wikiPageSourceHints(node.item),
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
    const language = normalizeLanguage(languageCode);
    if (!isBaseLanguage(language)) {
      await this.regeneratePageWithLlmFallback(
        repoId,
        slug,
        BASE_WIKI_LANGUAGE,
      );
      await this.translateWiki(repoId, BASE_WIKI_LANGUAGE, language);
      const page = await this.store.getDocPage(repoId, slug, language);
      if (!page) {
        throw new Error(`Translated catalog page not found: ${slug}`);
      }
      return translatedPageResult(page);
    }
    const catalog = await this.store.getLatestDocCatalog(repoId, language);
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
        language,
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
      languageCode: language,
      title: catalogItemTitle(node.item),
      kind: node.item.kind ?? "page",
      path: node.item.path ?? null,
      topic: wikiPageTopic(node.item),
      sourceHints: wikiPageSourceHints(node.item),
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
    const language = normalizeLanguage(languageCode);
    if (!isBaseLanguage(language)) {
      await this.updatePagesWithLlmFallback(
        repoId,
        BASE_WIKI_LANGUAGE,
        options,
      );
      await this.translateWiki(repoId, BASE_WIKI_LANGUAGE, language);
      const pages = await this.store.listDocPages(repoId, language);
      const sourceSlugs = (
        await this.store.listDocPages(repoId, BASE_WIKI_LANGUAGE)
      ).map((page) => page.slug);
      const deletedPageCount = await this.store.deleteDocPagesNotIn(
        repoId,
        sourceSlugs,
        language,
      );
      const results = pages.map(translatedPageResult);
      return this.updatePagesPayload(repoId, language, {
        results,
        reusedPages: [],
        staleSlugs: results
          .filter((result) => result.page.status !== "generated")
          .map((result) => result.page.slug),
        missingSlugs: [],
        metadataChangedSlugs: [],
        deletedPageCount,
      });
    }
    let catalog = await this.store.getLatestDocCatalog(repoId, language);
    if (!catalog) {
      catalog = (await this.generateCatalogWithLlmFallback(repoId, language))
        .catalog;
    }
    const result = await this.updatePagesForCatalog(
      repoId,
      language,
      catalog,
      true,
      options,
    );
    return this.updatePagesPayload(repoId, language, result);
  }

  translateWiki(
    repoId: string,
    sourceLanguage = "en",
    targetLanguage: string,
  ): Promise<JsonObject> {
    return translateWikiLanguage(
      this.store,
      this.llm,
      repoId,
      sourceLanguage,
      targetLanguage,
    );
  }

  async agentWikiPlan(
    repoId: string,
    languageCode = "en",
  ): Promise<JsonObject> {
    const language = normalizeLanguage(languageCode);
    const catalog = await this.store.getLatestDocCatalog(repoId, language);
    if (!catalog) {
      return {
        repo_id: repoId,
        language_code: language,
        status: "catalog_required",
        catalog: null,
        pages: [],
        catalog_evidence: await this.catalogGenerator.agentCatalogEvidence({
          repoId,
          languageCode: language,
        }),
        instructions:
          "Generate and save a catalog first, then call wiki plan again to get the page queue.",
      };
    }
    const nodes = catalogGenerationNodesFromStructure(catalog.structure);
    return {
      repo_id: repoId,
      language_code: language,
      status: "planned",
      catalog: catalogPayload(catalog),
      pages: nodes.map((node) => agentPageQueueItem(node)),
    };
  }

  async agentWikiCatalogEvidence(
    repoId: string,
    languageCode = "en",
  ): Promise<JsonObject> {
    const language = normalizeLanguage(languageCode);
    return this.catalogGenerator.agentCatalogEvidence({
      repoId,
      languageCode: language,
    });
  }

  async saveAgentWikiCatalog(
    repoId: string,
    catalogInput: string | JsonObject,
    languageCode = "en",
  ): Promise<JsonObject> {
    const language = normalizeLanguage(languageCode);
    const parsed = parseAgentCatalogInput(catalogInput);
    if (!parsed.payload) {
      return {
        repo_id: repoId,
        language_code: language,
        status: "invalid",
        validation_errors: parsed.validationErrors,
        catalog: null,
      };
    }
    const result = await this.catalogGenerator.saveAgentCatalog(
      { repoId, languageCode: language },
      parsed.payload,
    );
    return {
      repo_id: repoId,
      language_code: language,
      status: result.catalog ? "saved" : "invalid",
      validation_errors: result.validation_errors,
      catalog: result.catalog ? catalogPayload(result.catalog) : null,
    };
  }

  async validateAgentWikiCatalog(
    repoId: string,
    languageCode = "en",
    catalogInput?: string | JsonObject,
  ): Promise<JsonObject> {
    const language = normalizeLanguage(languageCode);
    const parsed =
      catalogInput === undefined
        ? { payload: undefined, validationErrors: [] }
        : parseAgentCatalogInput(catalogInput);
    if (parsed.validationErrors.length) {
      return {
        repo_id: repoId,
        language_code: language,
        status: "invalid",
        validation_errors: parsed.validationErrors,
        catalog: null,
      };
    }
    const result = await this.catalogGenerator.validateAgentCatalog(
      { repoId, languageCode: language },
      parsed.payload ?? undefined,
    );
    return {
      repo_id: repoId,
      language_code: language,
      status: result.validation_errors.length ? "invalid" : "valid",
      validation_errors: result.validation_errors,
      catalog: result.catalog ? catalogPayload(result.catalog) : null,
    };
  }

  async agentWikiEvidence(
    repoId: string,
    slug: string,
    languageCode = "en",
    options: { limit?: number } = {},
  ): Promise<JsonObject> {
    const language = normalizeLanguage(languageCode);
    const catalog = await this.requireAgentCatalog(repoId, language);
    const nodes = catalogGenerationNodesFromStructure(catalog.structure);
    const node = nodes.find((candidate) => candidate.slug === slug);
    if (!node) {
      throw new Error(`Catalog page not found: ${slug}`);
    }
    const query = agentEvidenceQuery(node);
    const trace = await this.graphRag.retrieve(repoId, query, {
      limit: positiveInt(options.limit, 12),
    });
    return agentEvidencePayload(repoId, language, catalog, nodes, node, trace);
  }

  async saveAgentWikiPage(
    repoId: string,
    slug: string,
    markdown: string,
    languageCode = "en",
    options: { title?: string; parentSlug?: string | null } = {},
  ): Promise<JsonObject> {
    const language = normalizeLanguage(languageCode);
    const catalog = await this.requireAgentCatalog(repoId, language);
    const nodes = catalogGenerationNodesFromStructure(catalog.structure);
    const node = nodes.find((candidate) => candidate.slug === slug) ?? null;
    const validationErrors = validateAgentMarkdown(markdown);
    if (!node) {
      validationErrors.push(`Catalog page not found: ${slug}`);
    }

    const allowedRefs = node
      ? allowedSourceRefsFromTrace(
          await this.graphRag.retrieve(repoId, agentEvidenceQuery(node), {
            limit: 12,
          }),
        )
      : [];
    const allowedByCitation = new Map(
      allowedRefs
        .map((ref): [string, JsonObject] | null =>
          typeof ref.citation_id === "string" ? [ref.citation_id, ref] : null,
        )
        .filter((entry): entry is [string, JsonObject] => Boolean(entry)),
    );
    const citations = extractMarkdownCitations(markdown);
    const sourceRefs: JsonObject[] = [];
    for (const citationId of citations) {
      const sourceRef = allowedByCitation.get(citationId);
      if (!sourceRef) {
        validationErrors.push(`Unknown source citation: [[${citationId}]]`);
        continue;
      }
      sourceRefs.push(sourceRef);
    }
    if (!citations.length) {
      validationErrors.push("Markdown must cite at least one evidence source.");
    }

    const page = await this.store.upsertDocPage({
      id: randomUUID(),
      repo_id: repoId,
      language_code: language,
      slug,
      title:
        options.title?.trim() ||
        (node ? catalogItemTitle(node.item) : titleFromAgentSlug(slug)),
      parent_slug: options.parentSlug ?? node?.parentSlug ?? null,
      markdown,
      source_refs: uniqueSourceRefs(sourceRefs),
      graph_refs: [],
      status: validationErrors.length ? "draft" : "generated",
      updated_at: new Date().toISOString(),
    });
    return {
      status: validationErrors.length ? "draft" : "generated",
      validation_errors: unique(validationErrors),
      page: pagePayload(page),
    };
  }

  async validateAgentWikiPage(
    repoId: string,
    slug: string,
    languageCode = "en",
  ): Promise<JsonObject> {
    const language = normalizeLanguage(languageCode);
    const catalog = await this.requireAgentCatalog(repoId, language);
    const nodes = catalogGenerationNodesFromStructure(catalog.structure);
    const validationErrors: string[] = [];
    if (!nodes.some((node) => node.slug === slug)) {
      validationErrors.push(`Catalog page not found: ${slug}`);
    }
    const page = await this.store.getDocPage(repoId, slug, language);
    if (!page) {
      validationErrors.push(`Wiki page not found: ${slug}`);
      return {
        repo_id: repoId,
        language_code: language,
        status: "invalid",
        validation_errors: unique(validationErrors),
        page: null,
      };
    }
    validationErrors.push(...validateAgentMarkdown(page.markdown));
    if (!page.title.trim()) {
      validationErrors.push("Page title must not be empty.");
    }
    const sourceCitationIds = new Set(
      page.source_refs
        .map((ref) => ref.citation_id)
        .filter((value): value is string => typeof value === "string"),
    );
    for (const citationId of extractMarkdownCitations(page.markdown)) {
      if (!sourceCitationIds.has(citationId)) {
        validationErrors.push(`Unknown source citation: [[${citationId}]]`);
      }
    }
    if (!sourceCitationIds.size) {
      validationErrors.push("Page must include source references.");
    }
    return {
      repo_id: repoId,
      language_code: language,
      status: validationErrors.length ? "invalid" : "valid",
      validation_errors: unique(validationErrors),
      page: pagePayload(page),
    };
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

  private async ensureBaseCatalogWithLlmFallback(
    repoId: string,
  ): Promise<DocCatalog> {
    const catalog = await this.store.getLatestDocCatalog(
      repoId,
      BASE_WIKI_LANGUAGE,
    );
    if (catalog) {
      return catalog;
    }
    return (
      await this.generateCatalogWithLlmFallback(repoId, BASE_WIKI_LANGUAGE)
    ).catalog;
  }

  private async requireAgentCatalog(
    repoId: string,
    languageCode: string,
  ): Promise<DocCatalog> {
    const catalog = await this.store.getLatestDocCatalog(repoId, languageCode);
    if (catalog) {
      return catalog;
    }
    throw new Error(
      "Agent wiki catalog not found. Generate catalog evidence and save an agent-written catalog before requesting page evidence.",
    );
  }

  private async ensureBasePagesWithLlmFallback(
    repoId: string,
  ): Promise<WikiPageResult[]> {
    await this.ensureBaseCatalogWithLlmFallback(repoId);
    const pages = await this.store.listDocPages(repoId, BASE_WIKI_LANGUAGE);
    if (pages.length) {
      return pages.map((page) => ({ page, validation_errors: [] }));
    }
    return this.generateAllPagesWithLlmFallback(repoId, BASE_WIKI_LANGUAGE);
  }

  private async translatedPageResults(
    repoId: string,
    languageCode: string,
  ): Promise<WikiPageResult[]> {
    return (await this.store.listDocPages(repoId, languageCode)).map(
      translatedPageResult,
    );
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
      kind: node.item.kind ?? "page",
      path: node.item.path ?? null,
      topic: wikiPageTopic(node.item),
      sourceHints: wikiPageSourceHints(node.item),
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

const BASE_WIKI_LANGUAGE = "en";

function normalizeLanguage(languageCode: string | undefined | null): string {
  return languageCode?.trim().toLowerCase() || BASE_WIKI_LANGUAGE;
}

function isBaseLanguage(languageCode: string): boolean {
  return normalizeLanguage(languageCode) === BASE_WIKI_LANGUAGE;
}

function translatedPageResult(page: DocPage): WikiPageResult {
  return {
    page,
    validation_errors:
      page.status === "draft"
        ? ["Translation failed; page was saved as a draft."]
        : [],
  };
}

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

function agentPageQueueItem(node: GenerationNode): JsonObject {
  return {
    slug: node.slug,
    title: catalogItemTitle(node.item),
    parent_slug: node.parentSlug,
    kind: node.item.kind ?? "page",
    topic: wikiPageTopic(node.item),
    path: node.item.path ?? null,
    source_hints: wikiPageSourceHints(node.item),
    order: node.order,
    has_children: node.hasChildren,
  };
}

function agentEvidenceQuery(node: GenerationNode): string {
  return [
    catalogItemTitle(node.item),
    wikiPageTopic(node.item),
    ...wikiPageSourceHints(node.item),
    node.slug,
  ]
    .filter(Boolean)
    .join(" ");
}

function agentEvidencePayload(
  repoId: string,
  languageCode: string,
  catalog: DocCatalog,
  nodes: GenerationNode[],
  node: GenerationNode,
  trace: RetrievalTrace,
): JsonObject {
  const parent = node.parentSlug
    ? nodes.find((candidate) => candidate.slug === node.parentSlug)
    : null;
  return {
    repo_id: repoId,
    language_code: languageCode,
    page: agentPageQueueItem(node),
    catalog_context: {
      catalog: catalogPayload(catalog),
      parent: parent ? agentPageQueueItem(parent) : null,
      children: nodes
        .filter((candidate) => candidate.parentSlug === node.slug)
        .map(agentPageQueueItem),
      siblings: nodes
        .filter(
          (candidate) =>
            candidate.parentSlug === node.parentSlug &&
            candidate.slug !== node.slug,
        )
        .map(agentPageQueueItem),
    },
    retrieval_trace: retrievalTracePayload(trace),
    allowed_source_refs: allowedSourceRefsFromTrace(trace),
    writing_brief: agentPageWritingBrief(node),
    instructions: [
      "Write a DeepWiki-style Markdown page from the returned evidence only.",
      'Start with "# {title}" and include "## Purpose and Scope" immediately after the title.',
      "Use concrete file, symbol, workflow, API, data, and boundary details from retrieval_trace and allowed_source_refs.",
      "Cite concrete code claims with [[S#]] markers from allowed_source_refs.",
      "Do not add Sources, Relevant source files, Related Pages, or Mermaid sections; CodeWiki renders source refs and graph context separately.",
      "If evidence is too thin, request more evidence for this slug instead of inventing details.",
    ],
  };
}

function agentPageWritingBrief(node: GenerationNode): JsonObject {
  return {
    title: catalogItemTitle(node.item),
    page_kind: node.item.kind ?? "page",
    path: node.item.path ?? null,
    topic: wikiPageTopic(node.item),
    required_sections: [
      "# {title}",
      "## Purpose and Scope",
      "one or more implementation-specific sections such as System Context, Core Components, Control Flow, Data Model, API Surface, Configuration, Extension Points, Failure Handling, or Operational Notes",
    ],
    required_detail_blocks: [
      "a Key Files or component responsibility table when multiple files or symbols are evidenced",
      "a workflow/control-flow table when calls, imports, routes, or execution steps are evidenced",
      "a boundary/dependency/configuration/failure-mode section when the evidence supports it",
    ],
    parent_page_guidance:
      node.hasChildren || node.item.kind === "category"
        ? "Synthesize how child pages relate, which responsibilities stay in each child, and where shared control flow, data contracts, or dependencies cross boundaries. Do not simply list child pages."
        : "Explain the concrete subsystem, workflow stage, public surface, data contract family, UI view, provider integration, export format, CLI flow, or extension point represented by this page.",
    citation_policy: [
      "Every factual claim about code should have a nearby [[S#]] citation.",
      "Use exact file paths from allowed_source_refs.",
      "Do not cite IDs that are absent from allowed_source_refs.",
    ],
    quality_bar: [
      "Avoid generic tutorial prose.",
      "Prefer short paragraphs and compact tables over long summaries.",
      "State missing evidence briefly instead of guessing.",
    ],
  };
}

function allowedSourceRefsFromTrace(trace: RetrievalTrace): JsonObject[] {
  const sourceChunks = trace.source_chunks.length
    ? trace.source_chunks
    : trace.chunks.map((chunk, index) => ({
        citation_id: `S${index + 1}`,
        file_path: chunk.file_path,
        start_line: chunk.start_line,
        end_line: chunk.end_line,
      }));
  return sourceChunks.map((chunk, index) => ({
    citation_id: stringJson(chunk.citation_id) ?? `S${index + 1}`,
    file_path: stringJson(chunk.file_path) ?? "",
    start_line: numberJson(chunk.start_line),
    end_line: numberJson(chunk.end_line),
  }));
}

function validateAgentMarkdown(markdown: string): string[] {
  const errors: string[] = [];
  const trimmed = markdown.trim();
  if (!trimmed) {
    errors.push("Markdown must not be empty.");
  }
  if (trimmed && !/^#\s+\S/m.test(trimmed)) {
    errors.push("Markdown must include an H1 title.");
  }
  if (trimmed && !/^##\s+Purpose and Scope\s*$/im.test(trimmed)) {
    errors.push(
      "markdown must include required heading: ## Purpose and Scope.",
    );
  }
  if (trimmed && !/\[\[S\d+]]/.test(trimmed)) {
    errors.push("Markdown must include at least one [[S#]] citation marker.");
  }
  if (trimmed && h2Headings(trimmed).length < 2) {
    errors.push(
      "Markdown must include at least one implementation detail section after Purpose and Scope.",
    );
  }
  if (trimmed && forbiddenAgentHeadings(trimmed).length) {
    errors.push(
      "Markdown must not include Sources, Relevant source files, Related Pages, or Mermaid sections.",
    );
  }
  if (trimmed && trimmed.length < 160) {
    errors.push("Markdown is too short to be useful.");
  }
  return errors;
}

function h2Headings(markdown: string): string[] {
  return [...markdown.matchAll(/^##\s+\S.*$/gm)].map((match) => match[0] ?? "");
}

function forbiddenAgentHeadings(markdown: string): string[] {
  return h2Headings(markdown).filter((heading) =>
    /^##\s+(Sources?|Relevant source files|Related Pages|Mermaid)\s*$/i.test(
      heading,
    ),
  );
}

function extractMarkdownCitations(markdown: string): string[] {
  return unique(
    [...markdown.matchAll(/\[\[(S\d+)]]/g)].map((match) => match[1] ?? ""),
  ).filter(Boolean);
}

function uniqueSourceRefs(refs: JsonObject[]): JsonObject[] {
  const byCitation = new Map<string, JsonObject>();
  for (const ref of refs) {
    const citationId = ref.citation_id;
    if (typeof citationId === "string" && !byCitation.has(citationId)) {
      byCitation.set(citationId, ref);
    }
  }
  return [...byCitation.values()];
}

function stringJson(value: JsonValue | undefined): string | null {
  return typeof value === "string" ? value : null;
}

function numberJson(value: JsonValue | undefined): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function parseAgentCatalogInput(input: string | JsonObject): {
  payload: JsonObject | null;
  validationErrors: string[];
} {
  if (isRecord(input)) {
    return { payload: input, validationErrors: [] };
  }
  const trimmed = input.trim();
  const candidate = stripMarkdownFence(trimmed) || extractJsonObject(trimmed);
  if (!candidate) {
    return {
      payload: null,
      validationErrors: ["Catalog input must be a JSON object."],
    };
  }
  try {
    const parsed = JSON.parse(candidate) as unknown;
    if (!isRecord(parsed)) {
      return {
        payload: null,
        validationErrors: ["Catalog input must be a JSON object."],
      };
    }
    return { payload: parsed as JsonObject, validationErrors: [] };
  } catch (error) {
    return {
      payload: null,
      validationErrors: [
        `Catalog input was not valid JSON: ${
          error instanceof Error ? error.message : String(error)
        }`,
      ],
    };
  }
}

function stripMarkdownFence(value: string): string {
  const fence = /^```(?:json)?\s*([\s\S]*?)\s*```$/i.exec(value);
  return fence?.[1]?.trim() ?? value;
}

function extractJsonObject(value: string): string | null {
  const start = value.indexOf("{");
  const end = value.lastIndexOf("}");
  return start >= 0 && end > start ? value.slice(start, end + 1) : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function positiveInt(value: number | undefined, fallback: number): number {
  return typeof value === "number" && Number.isInteger(value) && value > 0
    ? value
    : fallback;
}

function titleFromAgentSlug(slug: string): string {
  return slug
    .split("-")
    .filter(Boolean)
    .map((part) => part.slice(0, 1).toUpperCase() + part.slice(1))
    .join(" ");
}

function orderedResults(
  nodes: GenerationNode[],
  resultsBySlug: Map<string, WikiPageResult>,
): WikiPageResult[] {
  return nodes
    .map((node) => resultsBySlug.get(node.slug))
    .filter((result): result is WikiPageResult => Boolean(result));
}

function wikiPageTopic(item: CatalogItem): string {
  if (typeof item.topic === "string" && item.topic.trim()) {
    return item.topic.trim();
  }
  const title = catalogItemTitle(item);
  const path = typeof item.path === "string" ? item.path : "";
  return [title, path].filter(Boolean).join(" ");
}

function wikiPageSourceHints(item: CatalogItem): string[] {
  return Array.isArray(item.source_hints)
    ? item.source_hints.filter(
        (hint): hint is string =>
          typeof hint === "string" && hint.trim() !== "",
      )
    : [];
}
