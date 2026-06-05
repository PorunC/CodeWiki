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

  generateCatalog(repoId: string, languageCode = "en"): DocCatalog {
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

  generateAllPages(repoId: string, languageCode = "en"): WikiPageResult[] {
    let catalog = this.store.getLatestDocCatalog(repoId, languageCode);
    if (!catalog) {
      catalog = this.generateCatalog(repoId, languageCode);
    }
    const items = catalogPageItemsFromStructure(catalog.structure);
    const results: WikiPageResult[] = [];
    for (const item of items) {
      results.push({
        page: this.pageGenerator.generate({
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
        page: this.pageGenerator.generate({
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
    let catalog = this.store.getLatestDocCatalog(repoId, languageCode);
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

  regeneratePage(repoId: string, slug: string, languageCode = "en") {
    const catalog = this.store.getLatestDocCatalog(repoId, languageCode);
    const item = catalog ? findCatalogPageItem(catalog.structure, slug) : null;
    return {
      page: this.pageGenerator.generate({
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
    const catalog = this.store.getLatestDocCatalog(repoId, languageCode);
    const item = catalog ? findCatalogPageItem(catalog.structure, slug) : null;
    return this.pageGenerator.generateWithLlmFallback({
      repoId,
      slug,
      languageCode,
      title: item ? item.title : titleFromSlug(slug),
      path: item ? (item.path ?? null) : null,
    });
  }

  updatePages(repoId: string, languageCode = "en") {
    const results = this.generateAllPages(repoId, languageCode);
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
  ): JsonObject {
    return copyWikiLanguage(this.store, repoId, sourceLanguage, targetLanguage);
  }

  llmCachePayload(repoId: string, taskTypes: string[]): JsonObject {
    return llmCachePayloadForTasks(
      (taskType) => this.store.listLlmRuns(repoId, { taskType }),
      taskTypes,
    );
  }

  private updatePagesPayload(
    repoId: string,
    languageCode: string,
    results: WikiPageResult[],
  ) {
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
        chunk_count: this.store.listCodeChunks(repoId).length,
        errors: [],
      },
      llm_cache: this.llmCachePayload(repoId, ["catalog", "page"]),
    };
  }
}
