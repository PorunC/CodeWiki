import { randomUUID } from "node:crypto";
import type { CodeWikiStoreApi } from "../db/types.js";
import { type CachedLlmCompletion, type LlmOperation } from "../llm/cache.js";
import { dynamicJsonMessage, stableJsonMessage } from "../llm/messages.js";
import { loadPrompt } from "../services/prompts.js";
import type { DocCatalog, DocPage, JsonObject, JsonValue } from "../types.js";
import { catalogPayload, llmCachePayload, pagePayload } from "./payloads.js";

type WikiTranslationLlm = {
  isConfigured(taskType: string): boolean;
  complete(
    repoId: string,
    operation: LlmOperation,
  ): Promise<CachedLlmCompletion>;
};

type TranslationContentType = "catalog" | "page";

const TRANSLATION_ATTEMPTS = 3;
const TRANSLATION_MARKDOWN_CHUNK_CHARS = 8000;
const TRANSLATION_PROMPT_VERSION = "translation:wiki:v3";

export async function translateWikiLanguage(
  store: CodeWikiStoreApi,
  llm: WikiTranslationLlm | undefined,
  repoId: string,
  sourceLanguage: string,
  targetLanguage: string,
): Promise<JsonObject> {
  if (!llm?.isConfigured("translation")) {
    return copyWikiLanguage(store, repoId, sourceLanguage, targetLanguage);
  }
  return new WikiTranslator(store, llm).translateWiki(repoId, {
    sourceLanguage,
    targetLanguage,
  });
}

export async function copyWikiLanguage(
  store: CodeWikiStoreApi,
  repoId: string,
  sourceLanguage: string,
  targetLanguage: string,
): Promise<JsonObject> {
  const catalog = await store.getLatestDocCatalog(repoId, sourceLanguage);
  if (!catalog) {
    throw new Error(`Wiki catalog not found for language: ${sourceLanguage}`);
  }

  const pages = await store.listDocPages(repoId, sourceLanguage);
  const translatedCatalog = await store.saveDocCatalog(repoId, {
    title: catalog.title,
    language_code: targetLanguage,
    structure: catalog.structure,
  });
  const translatedPages: DocPage[] = [];
  for (const page of pages) {
    translatedPages.push(
      await Promise.resolve(
        store.upsertDocPage({
          ...page,
          id: randomUUID(),
          language_code: normalizeLanguage(targetLanguage),
        }),
      ),
    );
  }

  return translationPayload(
    store,
    repoId,
    sourceLanguage,
    targetLanguage,
    translatedCatalog,
    translatedPages,
  );
}

class WikiTranslator {
  constructor(
    private readonly store: CodeWikiStoreApi,
    private readonly llm: WikiTranslationLlm,
  ) {}

  async translateWiki(
    repoId: string,
    options: { sourceLanguage: string; targetLanguage: string },
  ): Promise<JsonObject> {
    const sourceLanguage = normalizeLanguage(options.sourceLanguage);
    const targetLanguage = normalizeLanguage(options.targetLanguage);
    if (sourceLanguage === targetLanguage) {
      throw new Error("source_language and target_language must be different.");
    }

    const sourceCatalog = await this.store.getLatestDocCatalog(
      repoId,
      sourceLanguage,
    );
    if (!sourceCatalog) {
      throw new Error(
        `Source catalog not found for language: ${sourceLanguage}`,
      );
    }

    const translatedCatalog = await this.translateCatalog(sourceCatalog, {
      sourceLanguage,
      targetLanguage,
    });
    const sourcePages = await this.store.listDocPages(repoId, sourceLanguage);
    const translatedPages: DocPage[] = [];
    for (const page of sourcePages) {
      translatedPages.push(
        await this.translatePage(page, { sourceLanguage, targetLanguage }),
      );
    }

    return translationPayload(
      this.store,
      repoId,
      sourceLanguage,
      targetLanguage,
      translatedCatalog,
      translatedPages,
    );
  }

  private async translateCatalog(
    catalog: DocCatalog,
    options: { sourceLanguage: string; targetLanguage: string },
  ): Promise<DocCatalog> {
    const sourceItems = arrayValue(catalog.structure.items);
    const payload: JsonObject = {
      content_type: "catalog",
      source_language: options.sourceLanguage,
      target_language: options.targetLanguage,
      title: catalog.title,
      items: catalogTitleEntries(sourceItems),
      style_guide: translationStyleGuide(options.targetLanguage),
      rules: [
        "Translate only human-facing title text.",
        "For Chinese targets, use concise natural Simplified Chinese documentation titles.",
        "Do not translate slugs, paths, topics, source_hints, or code identifiers.",
        "Return JSON with title and items containing path and title.",
      ],
    };
    const response = await this.completeTranslationJson(
      catalog.repo_id,
      payload,
      {
        cacheParts: [
          "catalog",
          catalog.id,
          options.sourceLanguage,
          options.targetLanguage,
        ],
        contentType: "catalog",
      },
    );
    const translatedStructure = {
      items: applyCatalogTitleTranslations(sourceItems, response.items),
    };
    validateCatalogPayload(translatedStructure);
    return this.store.saveDocCatalog(catalog.repo_id, {
      title: stringValue(response.title) || catalog.title,
      language_code: options.targetLanguage,
      structure: translatedStructure,
    });
  }

  private async translatePage(
    page: DocPage,
    options: { sourceLanguage: string; targetLanguage: string },
  ): Promise<DocPage> {
    try {
      const response = await this.translatePageResponse(page, options);
      return this.store.upsertDocPage({
        id: randomUUID(),
        repo_id: page.repo_id,
        language_code: options.targetLanguage,
        slug: page.slug,
        title: stringValue(response.title) || page.title,
        parent_slug: page.parent_slug,
        markdown: repairConjoinedFenceHeadings(
          stringValue(response.markdown) || page.markdown,
        ),
        source_refs: page.source_refs,
        graph_refs: page.graph_refs,
        status: page.status,
        updated_at: null,
      });
    } catch (error) {
      return this.saveTranslationDraft(page, {
        targetLanguage: options.targetLanguage,
        error: error instanceof Error ? error.message : String(error),
      });
    }
  }

  private async translatePageResponse(
    page: DocPage,
    options: { sourceLanguage: string; targetLanguage: string },
  ): Promise<JsonObject> {
    const chunks = markdownTranslationChunks(page.markdown);
    if (chunks.length <= 1) {
      return this.completeTranslationJson(
        page.repo_id,
        pageTranslationPayload(page, {
          ...options,
          markdown: page.markdown,
        }),
        {
          cacheParts: [
            "page",
            page.id,
            options.sourceLanguage,
            options.targetLanguage,
          ],
          contentType: "page",
        },
      );
    }

    const translatedChunks: string[] = [];
    let translatedTitle = page.title;
    for (const [index, chunk] of chunks.entries()) {
      const response = await this.completeTranslationJson(
        page.repo_id,
        pageTranslationPayload(page, {
          ...options,
          markdown: chunk,
          chunkIndex: index + 1,
          chunkCount: chunks.length,
        }),
        {
          cacheParts: [
            "page",
            page.id,
            options.sourceLanguage,
            options.targetLanguage,
            "chunk",
            index + 1,
            chunks.length,
          ],
          contentType: "page",
        },
      );
      if (index === 0) {
        translatedTitle = stringValue(response.title) || translatedTitle;
      }
      translatedChunks.push(stringValue(response.markdown) || chunk);
    }
    return {
      title: translatedTitle,
      markdown: translatedChunks
        .map((chunk) => chunk.trim())
        .filter(Boolean)
        .join("\n\n"),
    };
  }

  private async completeTranslationJson(
    repoId: string,
    payload: JsonObject,
    options: { cacheParts: unknown[]; contentType: TranslationContentType },
  ): Promise<JsonObject> {
    let attemptPayload = payload;
    let validationErrors: string[] = [];
    for (let attempt = 0; attempt < TRANSLATION_ATTEMPTS; attempt += 1) {
      const completion = await this.llm.complete(repoId, {
        taskType: "translation",
        cacheKey: translationCacheKey(options.cacheParts, attempt + 1),
        modelAlias: "translation",
        promptVersion: TRANSLATION_PROMPT_VERSION,
        inputPayload: attemptPayload,
        messages: translationMessages(attemptPayload, validationErrors),
        completion: { responseFormat: "json_object" },
      });
      const response = parseJsonObject(completion.result.content);
      validationErrors = validateTranslationResponse(
        response,
        options.contentType,
      );
      if (!validationErrors.length) {
        return response;
      }
      await this.store.updateLlmRunStatus(completion.run.id, {
        status: "error",
        error: validationErrors.join("; "),
      });
      attemptPayload = translationRepairPayload(
        payload,
        completion.result.content,
        validationErrors,
      );
    }
    throw new Error(
      `Translation LLM did not return a valid ${options.contentType} JSON object after repair attempts: ${validationErrors.join("; ")}`,
    );
  }

  private async saveTranslationDraft(
    page: DocPage,
    options: { targetLanguage: string; error: string },
  ): Promise<DocPage> {
    return this.store.upsertDocPage({
      id: randomUUID(),
      repo_id: page.repo_id,
      language_code: options.targetLanguage,
      slug: page.slug,
      title: page.title,
      parent_slug: page.parent_slug,
      markdown: translationDraftMarkdown(page, options.error),
      source_refs: page.source_refs,
      graph_refs: page.graph_refs,
      status: "draft",
      updated_at: null,
    });
  }
}

function pageTranslationPayload(
  page: DocPage,
  options: {
    sourceLanguage: string;
    targetLanguage: string;
    markdown: string;
    chunkIndex?: number | undefined;
    chunkCount?: number | undefined;
  },
): JsonObject {
  const rules = [
    "Translate prose and headings to the target language with natural local writing.",
    "For Chinese targets, rewrite awkward literal phrasing into fluent Chinese technical prose.",
    "Keep code blocks, inline code, file paths, URLs, anchors, and identifiers unchanged.",
    "Keep Markdown structure and links valid.",
    "Do not remove source citations or source sections.",
    "Return JSON with title and markdown.",
  ];
  const payload: JsonObject = {
    content_type: "page",
    source_language: options.sourceLanguage,
    target_language: options.targetLanguage,
    title: page.title,
    markdown: options.markdown,
    source_refs: page.source_refs,
    style_guide: translationStyleGuide(options.targetLanguage),
    rules,
  };
  if (options.chunkIndex !== undefined && options.chunkCount !== undefined) {
    payload.translation_chunk = {
      index: options.chunkIndex,
      count: options.chunkCount,
      scope:
        "Translate only this Markdown chunk. Return the translated chunk as markdown; do not summarize missing chunks or add cross-chunk framing.",
    };
    payload.rules = [
      ...rules,
      "This is one chunk of a longer page; preserve local Markdown structure only for this chunk.",
      "Do not add an extra page title unless the chunk already contains that heading.",
    ];
  }
  return payload;
}

function translationMessages(
  payload: JsonObject,
  validationErrors: string[] = [],
): LlmOperation["messages"] {
  let instruction =
    "Return only one valid JSON object for the requested translation shape. Do not include Markdown fences, comments, trailing commas, or prose outside JSON.";
  if (validationErrors.length) {
    instruction = `${instruction}\nRepair the previous response. Validation errors: ${JSON.stringify(validationErrors)}`;
  }
  return [
    {
      role: "system",
      content: translationSystemPrompt(),
    },
    {
      role: "user",
      content: stableJsonMessage("Stable translation contract", {
        instructions: instruction,
      }),
    },
    {
      role: "user",
      content: dynamicJsonMessage("Translation payload", payload),
    },
  ];
}

function translationSystemPrompt(): string {
  return loadPrompt("translation.md");
}

function translationRepairPayload(
  payload: JsonObject,
  previousResponse: string,
  validationErrors: string[],
): JsonObject {
  const contentType = stringValue(payload.content_type) || "translation";
  const shape =
    contentType === "catalog" ? "title and items" : "title and markdown";
  return {
    ...payload,
    previous_response: previousResponse.slice(0, 6000),
    validation_errors: validationErrors,
    repair_instructions: `Repair the ${contentType} translation. Return one valid JSON object only, with ${shape}. Preserve code identifiers, paths, URLs, slugs, anchors, and source links exactly as instructed.`,
  };
}

function translationStyleGuide(targetLanguage: string): JsonObject {
  const language = normalizeLanguage(targetLanguage);
  if (
    language === "zh" ||
    language === "cn" ||
    language === "zh-cn" ||
    language === "zh-hans" ||
    language.startsWith("zh-")
  ) {
    return {
      locale: "zh-Hans",
      voice: "natural Chinese technical documentation for developers in China",
      goals: [
        "Use fluent Simplified Chinese rather than word-for-word translation.",
        "Prefer concise headings and direct explanations.",
        "Keep Chinese sentence order natural; split long English sentences when needed.",
        "Use conventional Chinese technical terms while preserving common English terms.",
      ],
      avoid: [
        "machine-translation tone",
        "overusing 该, 此, 其, 进行, 通过...来, 被用于, 负责于",
        "stiff passive voice",
        "long 的 chains",
        "English-style modifier order",
      ],
      preferred_terms: {
        Overview: "概览",
        Architecture: "架构",
        "Reading Guide": "阅读指南",
        Dependencies: "依赖关系",
        "Relevant source files": "相关源文件",
        Sources: "来源",
        "Control Flow": "控制流程",
        "Data Model": "数据模型",
        "Failure Handling": "故障处理",
        Configuration: "配置",
        Operations: "运维",
        Testing: "测试",
      },
    };
  }
  return {
    locale: language,
    voice: "natural target-language technical documentation",
    goals: [
      "Localize prose instead of translating word-for-word.",
      "Keep headings concise and idiomatic.",
      "Preserve all technical identifiers and links exactly.",
    ],
  };
}

function catalogTitleEntries(items: unknown[]): JsonObject[] {
  const entries: JsonObject[] = [];
  for (const item of catalogItems(items)) {
    const path = catalogItemPath(item);
    entries.push({
      path,
      title: stringValue(item.title) || path,
    });
  }
  return entries;
}

function applyCatalogTitleTranslations(
  originalItems: unknown[],
  translatedItems: unknown,
): JsonObject[] {
  const translatedByPath = new Map<string, string>();
  for (const item of arrayValue(translatedItems)) {
    if (!isRecord(item)) {
      continue;
    }
    const path = stringValue(item.path);
    const title = stringValue(item.title);
    if (path && title) {
      translatedByPath.set(path, title);
    }
  }
  return originalItems
    .filter(isRecord)
    .map((item) => copyTranslatedCatalogItem(item, translatedByPath));
}

function copyTranslatedCatalogItem(
  item: Record<string, unknown>,
  translatedByPath: Map<string, string>,
): JsonObject {
  const copied: JsonObject = {};
  for (const [key, value] of Object.entries(item)) {
    if (key !== "children" && isJsonValue(value)) {
      copied[key] = value;
    }
  }
  const path = catalogItemPath(item);
  copied.title = translatedByPath.get(path) ?? stringValue(item.title) ?? path;
  copied.children = arrayValue(item.children)
    .filter(isRecord)
    .map((child) => copyTranslatedCatalogItem(child, translatedByPath));
  return copied;
}

function catalogItems(items: unknown[]): Record<string, unknown>[] {
  const result: Record<string, unknown>[] = [];
  const visit = (rawItems: unknown[]) => {
    for (const item of rawItems) {
      if (!isRecord(item)) {
        continue;
      }
      result.push(item);
      visit(arrayValue(item.children));
    }
  };
  visit(items);
  return result;
}

function catalogItemPath(item: Record<string, unknown>): string {
  return (
    stringValue(item.path) ||
    stringValue(item.slug) ||
    stringValue(item.title) ||
    ""
  );
}

function validateCatalogPayload(payload: JsonObject): void {
  if (!Array.isArray(payload.items)) {
    throw new Error("Catalog translation JSON must include an items array.");
  }
}

function validateTranslationResponse(
  response: JsonObject,
  contentType: TranslationContentType,
): string[] {
  const errors: string[] = [];
  if (!stringValue(response.title)) {
    errors.push("Translation JSON must include a non-empty title.");
  }
  if (contentType === "catalog" && !Array.isArray(response.items)) {
    errors.push("Catalog translation JSON must include an items array.");
  }
  if (contentType === "page" && !stringValue(response.markdown)) {
    errors.push("Page translation JSON must include non-empty markdown.");
  }
  return errors;
}

function parseJsonObject(content: string): JsonObject {
  const trimmed = stripMarkdownFence(content.trim());
  const candidates = [trimmed, extractObject(trimmed)].filter(
    (candidate): candidate is string => Boolean(candidate),
  );
  for (const candidate of candidates) {
    try {
      const parsed = JSON.parse(candidate) as unknown;
      if (isRecord(parsed)) {
        return jsonObject(parsed);
      }
    } catch {
      // Try the next candidate below.
    }
  }
  return {};
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

function markdownTranslationChunks(
  markdown: string,
  maxChars = TRANSLATION_MARKDOWN_CHUNK_CHARS,
): string[] {
  if (markdown.length <= maxChars) {
    return [markdown];
  }
  const chunks: string[] = [];
  let current = "";
  for (const block of markdownBlocks(markdown)) {
    if (!block) {
      continue;
    }
    if (block.length > maxChars) {
      if (current.trim()) {
        chunks.push(current.trim());
        current = "";
      }
      chunks.push(...splitLargeMarkdownBlock(block, maxChars));
      continue;
    }
    const separator = current && !current.endsWith("\n\n") ? "\n\n" : "";
    const candidate = current ? `${current}${separator}${block}` : block;
    if (candidate.length > maxChars && current.trim()) {
      chunks.push(current.trim());
      current = block;
    } else {
      current = candidate;
    }
  }
  if (current.trim()) {
    chunks.push(current.trim());
  }
  return chunks.length ? chunks : [markdown];
}

function markdownBlocks(markdown: string): string[] {
  const blocks: string[] = [];
  let current: string[] = [];
  let inFence = false;
  const flush = () => {
    if (current.length) {
      blocks.push(current.join("\n").trim());
      current = [];
    }
  };
  for (const line of markdown.split(/\r?\n/)) {
    const stripped = line.trimStart();
    const isFence = stripped.startsWith("```");
    const isHeading = stripped.startsWith("#") && !inFence;
    if (isHeading) {
      flush();
    }
    current.push(line);
    if (isFence) {
      inFence = !inFence;
    }
  }
  flush();
  return blocks;
}

function splitLargeMarkdownBlock(block: string, maxChars: number): string[] {
  const chunks: string[] = [];
  let current: string[] = [];
  let currentSize = 0;
  let inFence = false;
  for (const line of block.split(/\r?\n/)) {
    const lineSize = line.length + 1;
    if (current.length && !inFence && currentSize + lineSize > maxChars) {
      chunks.push(current.join("\n").trim());
      current = [];
      currentSize = 0;
    }
    current.push(line);
    currentSize += lineSize;
    if (line.trimStart().startsWith("```")) {
      inFence = !inFence;
    }
  }
  if (current.length) {
    chunks.push(current.join("\n").trim());
  }
  return chunks.filter(Boolean);
}

function translationDraftMarkdown(page: DocPage, error: string): string {
  const safeError = error.replace(/\0/g, "").trim();
  const message =
    safeError.length > 1200 ? `${safeError.slice(0, 1200)}...` : safeError;
  return [
    `# ${page.title}`,
    "> Translation failed after repair attempts. This draft keeps the source content so wiki generation can continue.",
    message ? `> Error: ${message}` : "> Error: translation failed.",
    page.markdown,
  ].join("\n\n");
}

function repairConjoinedFenceHeadings(markdown: string): string {
  return markdown.replace(/^([ \t]*`{3,})[ \t]*(#{1,6}[ \t]+)/gm, "$1\n$2");
}

async function translationPayload(
  store: CodeWikiStoreApi,
  repoId: string,
  sourceLanguage: string,
  targetLanguage: string,
  catalog: DocCatalog,
  pages: DocPage[],
): Promise<JsonObject> {
  return {
    repo_id: repoId,
    source_language: normalizeLanguage(sourceLanguage),
    target_language: normalizeLanguage(targetLanguage),
    status: pages.some((page) => page.status === "draft")
      ? "partial"
      : "translated",
    catalog: catalogPayload(catalog),
    page_count: pages.length,
    pages: pages.map(pagePayload),
    llm_cache: llmCachePayload(
      await store.listLlmRuns(repoId, { taskType: "translation" }),
    ),
  };
}

function translationCacheKey(cacheParts: unknown[], attempt: number): string {
  return `translation:v3:${[...cacheParts, "attempt", attempt]
    .map((part) => String(part).replace(/[:\s]+/g, "-"))
    .join(":")}`;
}

function normalizeLanguage(value: string | undefined | null): string {
  return value?.trim().toLowerCase() || "en";
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function arrayValue(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function jsonObject(value: Record<string, unknown>): JsonObject {
  const result: JsonObject = {};
  for (const [key, nested] of Object.entries(value)) {
    if (isJsonValue(nested)) {
      result[key] = nested;
    }
  }
  return result;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isJsonValue(value: unknown): value is JsonValue {
  if (
    value === null ||
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean"
  ) {
    return true;
  }
  if (Array.isArray(value)) {
    return value.every(isJsonValue);
  }
  return (
    typeof value === "object" &&
    value !== null &&
    Object.values(value).every(isJsonValue)
  );
}
