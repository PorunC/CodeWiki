import { randomUUID } from "node:crypto";
import type { CodeWikiStore } from "../db/store.js";
import type { JsonObject } from "../types.js";
import { catalogPayload, llmCachePayload, pagePayload } from "./payloads.js";

export function copyWikiLanguage(
  store: CodeWikiStore,
  repoId: string,
  sourceLanguage: string,
  targetLanguage: string,
): JsonObject {
  const catalog = store.getLatestDocCatalog(repoId, sourceLanguage);
  if (!catalog) {
    throw new Error(`Wiki catalog not found for language: ${sourceLanguage}`);
  }

  const pages = store.listDocPages(repoId, sourceLanguage);
  const translatedCatalog = store.saveDocCatalog(repoId, {
    title: catalog.title,
    language_code: targetLanguage,
    structure: catalog.structure,
  });
  const translatedPages = pages.map((page) =>
    store.upsertDocPage({
      ...page,
      id: randomUUID(),
      language_code: targetLanguage,
    }),
  );

  return {
    repo_id: repoId,
    source_language: sourceLanguage,
    target_language: targetLanguage,
    status: "translated",
    catalog: catalogPayload(translatedCatalog),
    page_count: translatedPages.length,
    pages: translatedPages.map(pagePayload),
    llm_cache: llmCachePayload(
      store.listLlmRuns(repoId, { taskType: "translation" }),
    ),
  };
}
