import type { CodeWikiStoreApi } from "../db/types.js";
import type { CachedLlmCompletion, LlmOperation } from "../llm/cache.js";
import type { DocCatalog, JsonObject } from "../types.js";
import {
  catalogPageItemsFromStructure,
  findCatalogPageItem,
  titleFromSlug,
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
    const items = catalogPageItemsFromStructure(catalog.structure);
    const results: WikiPageResult[] = [];
    for (const item of items) {
      results.push({
        page: await this.pageGenerator.generate({
          repoId,
          slug: item.slug,
          languageCode,
          title: item.title,
          path: item.path ?? null,
        }),
        validation_errors: [],
      });
    }
    if (!results.length) {
      results.push({
        page: await this.pageGenerator.generate({
          repoId,
          slug: "overview",
          languageCode,
          title: "Overview",
          path: null,
        }),
        validation_errors: [],
      });
    }
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
    const items = catalogPageItemsFromStructure(catalog.structure);
    const results: WikiPageResult[] = [];
    for (const item of items) {
      results.push(
        await this.pageGenerator.generateWithLlmFallback({
          repoId,
          slug: item.slug,
          languageCode,
          title: item.title,
          path: item.path ?? null,
        }),
      );
    }
    if (!results.length) {
      results.push(
        await this.pageGenerator.generateWithLlmFallback({
          repoId,
          slug: "overview",
          languageCode,
          title: "Overview",
          path: null,
        }),
      );
    }
    return results;
  }

  async regeneratePage(
    repoId: string,
    slug: string,
    languageCode = "en",
  ): Promise<WikiPageResult> {
    const catalog = await this.store.getLatestDocCatalog(repoId, languageCode);
    const item = catalog ? findCatalogPageItem(catalog.structure, slug) : null;
    return {
      page: await this.pageGenerator.generate({
        repoId,
        slug,
        languageCode,
        title: item ? item.title : titleFromSlug(slug),
        path: item ? (item.path ?? null) : null,
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
    const item = catalog ? findCatalogPageItem(catalog.structure, slug) : null;
    return this.pageGenerator.generateWithLlmFallback({
      repoId,
      slug,
      languageCode,
      title: item ? item.title : titleFromSlug(slug),
      path: item ? (item.path ?? null) : null,
    });
  }

  async updatePages(repoId: string, languageCode = "en"): Promise<JsonObject> {
    const results = await this.generateAllPages(repoId, languageCode);
    return this.updatePagesPayload(repoId, languageCode, results);
  }

  async updatePagesWithLlmFallback(repoId: string, languageCode = "en") {
    const results = await this.generateAllPagesWithLlmFallback(
      repoId,
      languageCode,
    );
    return this.updatePagesPayload(repoId, languageCode, results);
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
    const runs = (
      await Promise.all(
        taskTypes.map((taskType) =>
          this.store.listLlmRuns(repoId, { taskType }),
        ),
      )
    ).flat();
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
    results: WikiPageResult[],
  ): Promise<JsonObject> {
    return {
      repo_id: repoId,
      language_code: languageCode,
      status: results.length ? "updated" : "up_to_date",
      page_count: results.length,
      generated_count: results.length,
      reused_count: 0,
      stale_pages: [],
      missing_pages: [],
      metadata_changed_pages: [],
      generated_pages: results.map((result) => result.page.slug),
      deleted_page_count: 0,
      pages: results.map(pageResultPayload),
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
}
