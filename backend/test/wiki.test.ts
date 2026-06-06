import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { CodeWikiStore } from "../src/db/store.js";
import type { CachedLlmCompletion, LlmOperation } from "../src/llm/cache.js";
import type {
  CodeChunk,
  CodeGraphEdge,
  CodeGraphNode,
  JsonObject,
  LlmRun,
  RepoDescriptor,
} from "../src/types.js";
import { catalogItemsFromStructure } from "../src/wiki/catalog.js";
import { WikiService } from "../src/wiki/wikiService.js";

describe("WikiService", () => {
  let store: CodeWikiStore | null = null;

  afterEach(() => {
    store?.close();
    store = null;
  });

  it("builds directory catalogs, generated pages, and copied translations", async () => {
    const root = mkdtempSync(join(tmpdir(), "codewiki-wiki-"));
    store = new CodeWikiStore(join(root, "codewiki.sqlite3"));
    const repo = store.upsertRepo(repoDescriptor(root));
    store.replaceGraph(repo.id, {
      nodes: graphNodes(repo.id),
      edges: graphEdges(repo.id),
      chunks: codeChunks(repo.id),
    });

    const service = new WikiService(store);
    const catalog = await service.generateCatalog(repo.id);
    const items = catalog.structure.items;
    expect(Array.isArray(items)).toBe(true);
    expect(items).toEqual([
      expect.objectContaining({
        slug: "root",
        title: "Overview",
        path: null,
        topic: "1 files",
      }),
      expect.objectContaining({
        slug: "src",
        title: "Src",
        path: "src",
        topic: "2 files",
      }),
    ]);

    const pages = await service.generateAllPages(repo.id);
    const srcPage = pages.find((result) => result.page.slug === "src")?.page;
    expect(srcPage).toBeTruthy();
    expect(srcPage?.markdown).toContain("`helper` (function) in `src/util.ts`");
    expect(srcPage?.source_refs).toEqual([
      expect.objectContaining({
        citation_id: "S1",
        file_path: "src/util.ts",
        start_line: 1,
      }),
      expect.objectContaining({
        citation_id: "S2",
        file_path: "src/main.ts",
        start_line: 1,
      }),
    ]);

    const translated = await service.translateWiki(repo.id, "en", "zh");
    expect(translated).toMatchObject({
      repo_id: repo.id,
      source_language: "en",
      target_language: "zh",
      status: "translated",
      page_count: pages.length,
    });
    const translatedPage = store.getDocPage(repo.id, "src", "zh");
    expect(translatedPage?.language_code).toBe("zh");
    expect(translatedPage?.markdown).toBe(srcPage?.markdown);
    expect(translatedPage?.source_refs).toEqual(srcPage?.source_refs);
  });

  it("translates wiki catalogs and pages with the translation LLM contract", async () => {
    const root = mkdtempSync(join(tmpdir(), "codewiki-wiki-translation-llm-"));
    store = new CodeWikiStore(join(root, "codewiki.sqlite3"));
    const repo = store.upsertRepo(repoDescriptor(root));
    store.replaceGraph(repo.id, {
      nodes: graphNodes(repo.id),
      edges: graphEdges(repo.id),
      chunks: codeChunks(repo.id),
    });

    const sourceService = new WikiService(store);
    await sourceService.generateCatalog(repo.id);
    const pages = await sourceService.generateAllPages(repo.id);
    const sourcePage = store.getDocPage(repo.id, "src", "en");
    const llm = new FakeWikiLlm({
      translation: (operation) => translationCompletion(operation),
    });
    const service = new WikiService(store, llm);

    const translated = await service.translateWiki(repo.id, "en", "zh");

    expect(translated).toMatchObject({
      repo_id: repo.id,
      source_language: "en",
      target_language: "zh",
      status: "translated",
      page_count: pages.length,
    });
    const translatedCatalog = store.getLatestDocCatalog(repo.id, "zh");
    expect(translatedCatalog?.title).toBe("演示仓库 Wiki");
    expect(translatedCatalog?.structure.items).toEqual([
      expect.objectContaining({
        slug: "root",
        path: null,
        title: "概览",
      }),
      expect.objectContaining({
        slug: "src",
        path: "src",
        title: "源码",
      }),
    ]);
    const translatedPage = store.getDocPage(repo.id, "src", "zh");
    expect(translatedPage?.title).toBe("源码");
    expect(translatedPage?.markdown).toContain("已翻译 Src");
    expect(translatedPage?.markdown).toContain("`helper`");
    expect(translatedPage?.source_refs).toEqual(sourcePage?.source_refs);

    const operations = llm.operations.filter(
      (operation) => operation.taskType === "translation",
    );
    expect(operations).toHaveLength(1 + pages.length);
    expect(operations[0]).toMatchObject({
      promptVersion: "translation:wiki:v3",
      modelAlias: "translation",
      completion: { responseFormat: "json_object" },
    });
    expect(operations[0]?.cacheKey).toContain("translation:v3:catalog");
    expect(operations[0]?.inputPayload).toMatchObject({
      content_type: "catalog",
      target_language: "zh",
      style_guide: { locale: "zh-Hans" },
    });
    expect(operations[0]?.messages[0]?.content).toContain(
      "You are translating Code Wiki documentation.",
    );
    expect(operations[0]?.messages[1]?.content).toContain(
      "Stable translation contract",
    );
    expect(operations[0]?.messages[2]?.content).toContain(
      "Translation payload",
    );
  });

  it("generates requested non-base language pages via translation", async () => {
    const root = mkdtempSync(join(tmpdir(), "codewiki-wiki-generate-zh-"));
    store = new CodeWikiStore(join(root, "codewiki.sqlite3"));
    const repo = store.upsertRepo(repoDescriptor(root));
    store.replaceGraph(repo.id, {
      nodes: graphNodes(repo.id),
      edges: graphEdges(repo.id),
      chunks: codeChunks(repo.id),
    });
    const llm = new FakeWikiLlm({
      translation: (operation) => translationCompletion(operation),
    });
    const service = new WikiService(store, llm);

    const results = await service.generateAllPagesWithLlmFallback(
      repo.id,
      "zh",
    );

    expect(results.map((result) => result.page.language_code)).toEqual([
      "zh",
      "zh",
    ]);
    expect(results.map((result) => result.page.title)).toEqual([
      "概览",
      "源码",
    ]);
    expect(store.getDocPage(repo.id, "src", "en")?.title).toBe("Src");
    expect(store.getDocPage(repo.id, "src", "zh")?.title).toBe("源码");
    expect(store.listDocPages(repo.id, "en")).toHaveLength(2);
    expect(store.listDocPages(repo.id, "zh")).toHaveLength(2);
    expect(
      llm.operations.filter((operation) => operation.taskType === "page"),
    ).toHaveLength(0);
    expect(
      llm.operations.filter(
        (operation) => operation.taskType === "translation",
      ),
    ).toHaveLength(3);
  });

  it("uses provider-backed nested catalogs when a catalog LLM is configured", async () => {
    const root = mkdtempSync(join(tmpdir(), "codewiki-wiki-catalog-llm-"));
    store = new CodeWikiStore(join(root, "codewiki.sqlite3"));
    const repo = store.upsertRepo(repoDescriptor(root));
    store.replaceGraph(repo.id, {
      nodes: graphNodes(repo.id),
      edges: graphEdges(repo.id),
      chunks: codeChunks(repo.id),
    });

    const llm = new FakeWikiLlm({
      catalog: {
        title: "Provider Demo Wiki",
        items: [
          {
            title: "System Guide",
            slug: "system-guide",
            kind: "category",
            order: 0,
            children: [
              {
                title: "Runtime Flow",
                slug: "runtime-flow",
                kind: "page",
                path: "src",
                order: 0,
                topic: "How source files collaborate",
                source_hints: ["src/main.ts", "src/util.ts"],
              },
            ],
          },
        ],
      },
    });
    const service = new WikiService(store, llm);

    const result = await service.generateCatalogWithLlmFallback(repo.id);

    expect(result.catalog.title).toBe("Provider Demo Wiki");
    expect(result.validation_errors).toEqual([]);
    expect(result.llm).toMatchObject({
      status: "success",
      cache_hit: false,
      model: "fake/catalog",
    });
    const catalogItems = catalogItemsFromStructure(result.catalog.structure);
    expect(catalogItems.map((item) => item.slug)).toEqual([
      "overview",
      "architecture",
      "reading-guide",
      "dependencies",
      "system-guide",
    ]);
    expect(catalogItems.at(-1)).toEqual(
      expect.objectContaining({
        title: "System Guide",
        slug: "system-guide",
        kind: "category",
        children: [
          expect.objectContaining({
            title: "Runtime Flow",
            slug: "runtime-flow",
            kind: "page",
            path: "src",
          }),
        ],
      }),
    );
    expect(llm.operations[0]?.inputPayload.repo).toMatchObject({
      name: "Demo Repo",
    });
    expect(llm.operations[0]?.inputPayload).not.toHaveProperty("repo_name");
    expect(llm.operations[0]?.inputPayload).not.toHaveProperty("local_items");
    const requiredShape = jsonObject(
      llm.operations[0]?.inputPayload.required_json_shape,
    );
    const backendShape = jsonObjectArray(requiredShape.items).find(
      (item) => item.slug === "backend-services",
    );
    const wikiShape = jsonObjectArray(backendShape?.children).find(
      (item) => item.slug === "wiki-generation",
    );
    const catalogShape = jsonObjectArray(wikiShape?.children).find(
      (item) => item.slug === "catalog-planning",
    );
    expect(backendShape).toMatchObject({
      title: "Backend Services",
      kind: "category",
    });
    expect(wikiShape).toMatchObject({
      title: "Wiki Generation",
      kind: "category",
    });
    expect(catalogShape).toMatchObject({
      title: "Catalog Planning",
      slug: "catalog-planning",
    });

    const pages = await service.generateAllPagesWithLlmFallback(repo.id);
    const systemPage = pages.find(
      (page) => page.page.slug === "system-guide",
    )?.page;
    const runtimePage = pages.find(
      (page) => page.page.slug === "runtime-flow",
    )?.page;

    expect(pages.map((page) => page.page.slug)).toEqual([
      "overview",
      "architecture",
      "reading-guide",
      "dependencies",
      "system-guide",
      "runtime-flow",
    ]);
    expect(systemPage?.parent_slug).toBeNull();
    expect(systemPage?.markdown).toContain("## Child Pages");
    expect(systemPage?.markdown).toContain("Runtime Flow");
    expect(runtimePage?.parent_slug).toBe("system-guide");
    expect(runtimePage?.title).toBe("Runtime Flow");
    expect(runtimePage?.markdown).toContain(
      "`helper` (function) in `src/util.ts`",
    );
    expect(llm.operations[0]?.promptVersion).toBe("catalog:deepwiki:v4");
    expect(llm.operations[0]?.cacheKey).toContain("catalog:v4:");
    expect(llm.operations[0]?.inputPayload.community_hierarchy).toEqual([]);
    expect(llm.operations[0]?.messages[0]?.content).toContain(
      "Analysis workflow:",
    );
  });

  it("falls back to the local catalog when provider catalog JSON is invalid", async () => {
    const root = mkdtempSync(join(tmpdir(), "codewiki-wiki-catalog-fallback-"));
    store = new CodeWikiStore(join(root, "codewiki.sqlite3"));
    const repo = store.upsertRepo(repoDescriptor(root));
    store.replaceGraph(repo.id, {
      nodes: graphNodes(repo.id),
      edges: graphEdges(repo.id),
      chunks: codeChunks(repo.id),
    });

    const service = new WikiService(
      store,
      new FakeWikiLlm({ catalog: "this is not json" }),
    );

    const result = await service.generateCatalogWithLlmFallback(repo.id);

    expect(result.catalog.title).toBe("Demo Repo Wiki");
    expect(result.validation_errors).toEqual([
      "LLM catalog response was not valid JSON.",
    ]);
    expect(result.llm).toMatchObject({
      status: "fallback",
      error: "LLM catalog response was not valid JSON.",
    });
    expect(result.catalog.structure.items).toEqual([
      expect.objectContaining({ slug: "root", title: "Overview" }),
      expect.objectContaining({ slug: "src", title: "Src" }),
    ]);
  });

  it("generates nested pages from catalog items with derived slugs", async () => {
    const root = mkdtempSync(join(tmpdir(), "codewiki-wiki-derived-slugs-"));
    store = new CodeWikiStore(join(root, "codewiki.sqlite3"));
    const repo = store.upsertRepo(repoDescriptor(root));
    store.replaceGraph(repo.id, {
      nodes: graphNodes(repo.id),
      edges: graphEdges(repo.id),
      chunks: codeChunks(repo.id),
    });
    store.saveDocCatalog(repo.id, {
      title: "Derived Slug Wiki",
      structure: {
        items: [
          {
            title: "System Guide",
            kind: "category",
            children: [
              {
                title: "Runtime Flow",
                kind: "page",
                path: "src",
              },
            ],
          },
        ],
      },
    });

    const service = new WikiService(store);
    const pages = await service.generateAllPages(repo.id);

    expect(pages.map((page) => page.page.slug)).toEqual([
      "system-guide",
      "src",
    ]);
    expect(store.getDocPage(repo.id, "system-guide")?.markdown).toContain(
      "Runtime Flow",
    );
    expect(store.getDocPage(repo.id, "src")?.parent_slug).toBe("system-guide");
  });

  it("updates only stale pages and their catalog ancestors", async () => {
    const root = mkdtempSync(join(tmpdir(), "codewiki-wiki-incremental-"));
    store = new CodeWikiStore(join(root, "codewiki.sqlite3"));
    const repo = store.upsertRepo(repoDescriptor(root));
    store.replaceGraph(repo.id, {
      nodes: graphNodes(repo.id),
      edges: graphEdges(repo.id),
      chunks: codeChunks(repo.id),
    });
    store.saveDocCatalog(repo.id, {
      title: "Incremental Wiki",
      structure: {
        items: [
          {
            title: "System Guide",
            slug: "system-guide",
            kind: "category",
            children: [
              {
                title: "Runtime Flow",
                slug: "runtime-flow",
                kind: "page",
                path: "src",
              },
              {
                title: "API Reference",
                slug: "api-reference",
                kind: "page",
                path: "src",
              },
            ],
          },
        ],
      },
    });

    const service = new WikiService(store);
    await service.generateAllPages(repo.id);
    const firstApiUpdatedAt = store.getDocPage(
      repo.id,
      "api-reference",
    )?.updated_at;

    const update = await service.updatePages(repo.id, "en", {
      staleSlugs: ["runtime-flow"],
    });

    expect(update).toMatchObject({
      status: "updated",
      generated_count: 2,
      reused_count: 1,
      stale_pages: ["runtime-flow"],
      missing_pages: [],
      metadata_changed_pages: [],
      generated_pages: ["system-guide", "runtime-flow"],
    });
    expect(store.getDocPage(repo.id, "system-guide")?.markdown).toContain(
      "Runtime Flow",
    );
    expect(store.getDocPage(repo.id, "api-reference")?.updated_at).toBe(
      firstApiUpdatedAt,
    );
  });

  it("deletes generated pages that are no longer in the catalog", async () => {
    const root = mkdtempSync(join(tmpdir(), "codewiki-wiki-delete-loose-"));
    store = new CodeWikiStore(join(root, "codewiki.sqlite3"));
    const repo = store.upsertRepo(repoDescriptor(root));
    store.replaceGraph(repo.id, {
      nodes: graphNodes(repo.id),
      edges: graphEdges(repo.id),
      chunks: codeChunks(repo.id),
    });
    store.saveDocCatalog(repo.id, {
      title: "Loose Page Wiki",
      structure: {
        items: [
          {
            title: "Runtime Flow",
            slug: "runtime-flow",
            kind: "page",
            path: "src",
          },
        ],
      },
    });

    const service = new WikiService(store);
    await service.generateAllPages(repo.id);
    store.upsertDocPage({
      id: "loose-page",
      repo_id: repo.id,
      language_code: "en",
      slug: "old-page",
      title: "Old Page",
      parent_slug: null,
      markdown: "# Old Page",
      source_refs: [],
      graph_refs: [],
      status: "generated",
      updated_at: "2026-01-01T00:00:00.000Z",
    });

    const update = await service.updatePages(repo.id);

    expect(update).toMatchObject({
      status: "updated",
      deleted_page_count: 1,
    });
    expect(store.getDocPage(repo.id, "runtime-flow")).toBeTruthy();
    expect(store.getDocPage(repo.id, "old-page")).toBeNull();
  });

  it("plans, evidences, saves, and validates agent-generated wiki pages", async () => {
    const root = mkdtempSync(join(tmpdir(), "codewiki-wiki-agent-"));
    store = new CodeWikiStore(join(root, "codewiki.sqlite3"));
    const repo = store.upsertRepo(repoDescriptor(root));
    store.replaceGraph(repo.id, {
      nodes: graphNodes(repo.id),
      edges: graphEdges(repo.id),
      chunks: codeChunks(repo.id),
    });

    const service = new WikiService(store);
    const plan = await service.agentWikiPlan(repo.id);

    expect(plan).toMatchObject({
      repo_id: repo.id,
      language_code: "en",
    });
    expect(jsonObjectArray(plan.pages).map((page) => page.slug)).toEqual([
      "root",
      "src",
    ]);

    const evidence = await service.agentWikiEvidence(repo.id, "src");
    const allowedSourceRefs = jsonObjectArray(evidence.allowed_source_refs);
    expect(allowedSourceRefs[0]).toMatchObject({
      citation_id: "S1",
    });
    expect(typeof allowedSourceRefs[0]?.file_path).toBe("string");
    expect(allowedSourceRefs[0]?.file_path).toMatch(/^src\//);
    expect(jsonObject(evidence.retrieval_trace).query).toContain("Src");

    const saved = await service.saveAgentWikiPage(
      repo.id,
      "src",
      [
        "# Src",
        "",
        "The `src` directory contains TypeScript runtime code and the helper implementation. [[S1]]",
      ].join("\n"),
      "en",
      { title: "Src" },
    );
    expect(saved.status).toBe("generated");
    expect(saved.validation_errors).toEqual([]);
    expect(store.getDocPage(repo.id, "src")?.source_refs).toEqual([
      expect.objectContaining({ citation_id: "S1" }),
    ]);

    const valid = await service.validateAgentWikiPage(repo.id, "src");
    expect(valid.status).toBe("valid");
    expect(valid.validation_errors).toEqual([]);

    const invalid = await service.saveAgentWikiPage(
      repo.id,
      "missing",
      "# Missing\n\nUnsupported claim. [[S99]]",
    );
    expect(invalid.status).toBe("draft");
    expect(stringArray(invalid.validation_errors)).toEqual(
      expect.arrayContaining([
        "Catalog page not found: missing",
        "Unknown source citation: [[S99]]",
      ]),
    );
  });

  it("lazily builds GraphRAG chunks when wiki page generation starts from graph-only data", async () => {
    const root = mkdtempSync(join(tmpdir(), "codewiki-wiki-lazy-chunks-"));
    writeDemoSourceFiles(root);
    store = new CodeWikiStore(join(root, "codewiki.sqlite3"));
    const repo = store.upsertRepo(repoDescriptor(root));
    store.replaceGraph(repo.id, {
      nodes: graphNodes(repo.id),
      edges: graphEdges(repo.id),
      chunks: [],
    });
    store.saveDocCatalog(repo.id, {
      title: "Lazy Wiki",
      structure: {
        items: [
          {
            title: "Runtime Flow",
            slug: "runtime-flow",
            kind: "page",
            path: "src",
            topic: "helper runtime flow",
            source_hints: ["src/util.ts"],
          },
        ],
      },
    });

    const [result] = await new WikiService(store).generateAllPages(repo.id);

    expect(store.listCodeChunks(repo.id).length).toBeGreaterThanOrEqual(1);
    expect(result?.page.slug).toBe("runtime-flow");
    expect(result?.page.markdown).toContain("`helper` (function)");
    expect(result?.page.source_refs).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          file_path: "src/util.ts",
          start_line: 1,
        }),
      ]),
    );
  });

  it("renders LLM pages with server diagrams, source URLs, and grouped sources", async () => {
    const root = mkdtempSync(join(tmpdir(), "codewiki-wiki-page-rendering-"));
    writeDemoSourceFiles(root);
    store = new CodeWikiStore(join(root, "codewiki.sqlite3"));
    const repo = store.upsertRepo({
      ...repoDescriptor(root),
      git_url: "git@github.com:acme/demo.git",
      commit_hash: "abc123",
    });
    store.replaceGraph(repo.id, {
      nodes: graphNodes(repo.id),
      edges: [
        ...graphEdges(repo.id),
        {
          id: "edge-main-imports-util",
          repo_id: repo.id,
          source_id: "main-file",
          target_id: "util-file",
          type: "imports",
          confidence: 1,
          weight: 1,
          is_inferred: false,
          metadata: {},
        },
      ],
      chunks: codeChunks(repo.id),
    });
    store.saveDocCatalog(repo.id, {
      title: "Rendered Wiki",
      structure: {
        items: [
          {
            title: "Main Runtime",
            slug: "main-runtime",
            kind: "page",
            path: "src",
            topic: "src/main.ts",
            source_hints: ["src/main.ts", "src/util.ts"],
          },
        ],
      },
    });
    const llm = new FakeWikiLlm({
      page: {
        title: "Main Runtime",
        markdown: [
          "# Main Runtime",
          "",
          "## Purpose and Scope",
          "",
          "The runtime calls the helper. [[S1]]",
          "",
          "```mermaid",
          "flowchart TD",
          "  invented --> graph",
          "```",
          "",
          "Sources: this inline source line should be removed.",
        ].join("\n"),
        source_refs: [{ citation_id: "S1" }],
      },
    });
    const service = new WikiService(store, llm);

    const [result] = await service.generateAllPagesWithLlmFallback(repo.id);
    const page = result?.page;

    expect(page?.status).toBe("generated");
    expect(page?.markdown).not.toContain("invented --> graph");
    expect(page?.markdown).not.toContain("Sources: this inline source line");
    expect(page?.markdown).toContain(
      "### Main Runtime component relationships",
    );
    expect(page?.markdown).toContain("```mermaid");
    expect(page?.markdown).toContain(
      "- [src/main.ts](https://github.com/acme/demo/blob/abc123/src/main.ts)",
    );
    expect(page?.markdown).toContain(
      "[S1](https://github.com/acme/demo/blob/abc123/src/util.ts#L1-L3",
    );
    expect(page?.markdown).toContain("## Sources");
    expect(page?.markdown).toContain(
      "  - S1 [L1-L3](https://github.com/acme/demo/blob/abc123/src/util.ts#L1-L3)",
    );
    expect(page?.source_refs[0]).toMatchObject({
      citation_id: "S1",
      file_path: "src/util.ts",
      start_line: 1,
      end_line: 3,
      read_via: "ReadFile",
      source_url: "https://github.com/acme/demo/blob/abc123/src/util.ts#L1-L3",
    });
    const pageOperation = llm.operations.find(
      (operation) => operation.taskType === "page",
    );
    const diagramSlots = jsonObjectArray(
      pageOperation?.inputPayload.diagram_slots,
    );
    const componentSlot = diagramSlots.find(
      (slot) => slot.slot === "component-relationships",
    );
    const implementationSlot = diagramSlots.find(
      (slot) => slot.slot === "implementation-flow",
    );
    expect(componentSlot).toMatchObject({
      slot: "component-relationships",
      placeholder: "[[DIAGRAM:component-relationships]]",
      kind: "component",
    });
    expect(typeof componentSlot?.reason).toBe("string");
    expect(stringArray(componentSlot?.source_edge_ids)).toContain(
      "edge-main-imports-util",
    );
    expect(implementationSlot).toMatchObject({
      slot: "implementation-flow",
      placeholder: "[[DIAGRAM:implementation-flow]]",
      kind: "symbol_flow",
    });
    expect(typeof implementationSlot?.reason).toBe("string");
    expect(stringArray(implementationSlot?.source_edge_ids)).toContain(
      "edge-main-imports-util",
    );
  });

  it("saves draft pages when LLM source refs fail strict validation", async () => {
    const root = mkdtempSync(join(tmpdir(), "codewiki-wiki-page-draft-"));
    writeDemoSourceFiles(root);
    store = new CodeWikiStore(join(root, "codewiki.sqlite3"));
    const repo = store.upsertRepo(repoDescriptor(root));
    store.replaceGraph(repo.id, {
      nodes: graphNodes(repo.id),
      edges: graphEdges(repo.id),
      chunks: codeChunks(repo.id),
    });
    store.saveDocCatalog(repo.id, {
      title: "Draft Wiki",
      structure: {
        items: [
          {
            title: "Main Runtime",
            slug: "main-runtime",
            kind: "page",
            path: "src",
            topic: "src/main.ts",
            source_hints: ["src/main.ts"],
          },
        ],
      },
    });
    const service = new WikiService(
      store,
      new FakeWikiLlm({
        page: {
          title: "Main Runtime",
          markdown:
            "# Main Runtime\n\n## Purpose and Scope\n\nUnsupported claim.",
          source_refs: [
            { file_path: "missing.ts", start_line: 1, end_line: 1 },
          ],
        },
      }),
    );

    const [result] = await service.generateAllPagesWithLlmFallback(repo.id);

    expect(result?.page.status).toBe("draft");
    expect(result?.page.source_refs).toEqual([]);
    expect(result?.page.markdown).toContain("## Validation Errors");
    expect(result?.validation_errors).toContain(
      "source_refs[0] file does not exist in repo: missing.ts.",
    );
    expect(result?.validation_errors).toContain(
      "At least one valid source_ref is required.",
    );
  });

  it("uses the main-compatible JSON repair payload after malformed page JSON", async () => {
    const root = mkdtempSync(join(tmpdir(), "codewiki-wiki-page-json-repair-"));
    writeDemoSourceFiles(root);
    store = new CodeWikiStore(join(root, "codewiki.sqlite3"));
    const repo = store.upsertRepo(repoDescriptor(root));
    store.replaceGraph(repo.id, {
      nodes: graphNodes(repo.id),
      edges: graphEdges(repo.id),
      chunks: codeChunks(repo.id),
    });
    store.saveDocCatalog(repo.id, {
      title: "Repair Wiki",
      structure: {
        items: [
          {
            title: "Main Runtime",
            slug: "main-runtime",
            kind: "page",
            path: "src",
            topic: "src/main.ts",
            source_hints: ["src/util.ts"],
          },
        ],
      },
    });
    let attempts = 0;
    const llm = new FakeWikiLlm({
      page: () => {
        attempts += 1;
        if (attempts === 1) {
          return "not json";
        }
        return {
          title: "Main Runtime",
          markdown:
            "# Main Runtime\n\n## Purpose and Scope\n\nThe runtime uses helper. [[S1]]",
          source_refs: [{ citation_id: "S1" }],
        };
      },
    });
    const service = new WikiService(store, llm);

    const [result] = await service.generateAllPagesWithLlmFallback(repo.id);

    expect(result?.page.status).toBe("generated");
    expect(llm.operations.filter((op) => op.taskType === "page")).toHaveLength(
      2,
    );
    const repairPayload = llm.operations[1]?.inputPayload;
    expect(repairPayload).toMatchObject({
      previous_response: "not json",
      validation_errors: ["LLM did not return a JSON object."],
      repair_instructions:
        "Repair the page response. Return one valid JSON object only, with title, markdown, and source_refs. Use only diagram placeholders listed in diagram_slots. Do not include prose, comments, Markdown fences around the JSON, or trailing commas.",
    });
  });

  it("uses the main-compatible validation repair payload after page validation errors", async () => {
    const root = mkdtempSync(
      join(tmpdir(), "codewiki-wiki-page-validation-repair-"),
    );
    writeDemoSourceFiles(root);
    store = new CodeWikiStore(join(root, "codewiki.sqlite3"));
    const repo = store.upsertRepo(repoDescriptor(root));
    store.replaceGraph(repo.id, {
      nodes: graphNodes(repo.id),
      edges: graphEdges(repo.id),
      chunks: codeChunks(repo.id),
    });
    store.saveDocCatalog(repo.id, {
      title: "Repair Wiki",
      structure: {
        items: [
          {
            title: "Main Runtime",
            slug: "main-runtime",
            kind: "page",
            path: "src",
            topic: "src/main.ts",
            source_hints: ["src/util.ts"],
          },
        ],
      },
    });
    const invalidResponse = {
      title: "Main Runtime",
      markdown: "# Main Runtime\n\nMissing the required section. [[S1]]",
      source_refs: [{ citation_id: "S1" }],
    };
    let attempts = 0;
    const llm = new FakeWikiLlm({
      page: () => {
        attempts += 1;
        if (attempts === 1) {
          return invalidResponse;
        }
        return {
          title: "Main Runtime",
          markdown:
            "# Main Runtime\n\n## Purpose and Scope\n\nThe runtime uses helper. [[S1]]",
          source_refs: [{ citation_id: "S1" }],
        };
      },
    });
    const service = new WikiService(store, llm);

    const [result] = await service.generateAllPagesWithLlmFallback(repo.id);

    expect(result?.page.status).toBe("generated");
    expect(llm.operations.filter((op) => op.taskType === "page")).toHaveLength(
      2,
    );
    const repairPayload = llm.operations[1]?.inputPayload;
    expect(repairPayload).toMatchObject({
      previous_response: invalidResponse,
      validation_errors: [
        "markdown must include required heading: ## Purpose and Scope.",
      ],
      repair_instructions:
        "Repair the page so it validates. Keep the same title, include the required Purpose and Scope section, choose source_refs from allowed_source_refs, and only use [[S#]] markers for source_refs you return. Remove any unknown diagram placeholder, or use exact placeholders from diagram_slots.",
    });
  });
});

type FakeCompletion =
  | JsonObject
  | string
  | ((operation: LlmOperation) => JsonObject | string);

class FakeWikiLlm {
  readonly operations: LlmOperation[] = [];

  constructor(private readonly completions: Record<string, FakeCompletion>) {}

  isConfigured(taskType: string): boolean {
    return Object.hasOwn(this.completions, taskType);
  }

  async complete(
    repoId: string,
    operation: LlmOperation,
  ): Promise<CachedLlmCompletion> {
    this.operations.push(operation);
    const completion = this.completions[operation.taskType];
    if (completion === undefined) {
      throw new Error(`Unexpected LLM task: ${operation.taskType}`);
    }
    const resolved =
      typeof completion === "function" ? completion(operation) : completion;
    const content =
      typeof resolved === "string" ? resolved : JSON.stringify(resolved);
    return {
      result: {
        content,
        model: `fake/${operation.taskType}`,
        provider: "fake",
        usage: {
          prompt_tokens: 12,
          completion_tokens: 8,
        },
      },
      run: fakeLlmRun(repoId, operation, content),
      cacheHit: false,
    };
  }
}

function fakeLlmRun(
  repoId: string,
  operation: LlmOperation,
  content: string,
): LlmRun {
  return {
    id: `llm-${operation.taskType}`,
    repo_id: repoId,
    task_type: operation.taskType,
    provider: "fake",
    model: `fake/${operation.taskType}`,
    model_alias: operation.modelAlias ?? null,
    prompt_version: operation.promptVersion ?? null,
    input_hash: "fake-input-hash",
    cache_key: operation.cacheKey,
    tokens_in: 12,
    tokens_out: 8,
    cost_usd: null,
    duration_ms: 1,
    response_content: content,
    response_usage: {
      prompt_tokens: 12,
      completion_tokens: 8,
    },
    cached: false,
    status: "success",
    error: null,
    created_at: "2026-01-01T00:00:00.000Z",
  };
}

function translationCompletion(operation: LlmOperation): JsonObject {
  const contentType = payloadString(operation.inputPayload.content_type);
  if (contentType === "catalog") {
    return {
      title: "演示仓库 Wiki",
      items: [
        { path: "root", title: "概览" },
        { path: "src", title: "源码" },
      ],
    };
  }
  const title = payloadString(operation.inputPayload.title);
  const translatedTitle =
    title === "Src" ? "源码" : title === "Overview" ? "概览" : title;
  return {
    title: translatedTitle,
    markdown: [
      `# ${translatedTitle}`,
      "",
      "## Purpose and Scope",
      "",
      `已翻译 ${title}，保留 \`helper\` 与 [[S1]].`,
    ].join("\n"),
  };
}

function payloadString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function jsonObjectArray(value: unknown): JsonObject[] {
  return Array.isArray(value) ? value.filter(isJsonObject) : [];
}

function jsonObject(value: unknown): JsonObject {
  return isJsonObject(value) ? value : {};
}

function isJsonObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

function repoDescriptor(root: string): RepoDescriptor {
  return {
    id: "repo-1",
    name: "Demo Repo",
    path: root,
    source_type: "local",
    git_url: null,
    commit_hash: null,
  };
}

function writeDemoSourceFiles(root: string): void {
  mkdirSync(join(root, "src"), { recursive: true });
  writeFileSync(
    join(root, "src/main.ts"),
    "export function run() {\n  return helper(41);\n}\n",
  );
  writeFileSync(
    join(root, "src/util.ts"),
    "export function helper(x: number) {\n  return x + 1;\n}\n",
  );
}

function graphNodes(repoId: string): CodeGraphNode[] {
  return [
    node(
      repoId,
      "readme",
      "config",
      "README.md",
      "README.md",
      "markdown",
      "README.md",
    ),
    node(
      repoId,
      "main-file",
      "file",
      "src/main.ts",
      "src/main.ts",
      "typescript",
      "src/main.ts",
    ),
    node(
      repoId,
      "util-file",
      "file",
      "src/util.ts",
      "src/util.ts",
      "typescript",
      "src/util.ts",
    ),
    node(
      repoId,
      "helper",
      "function",
      "helper",
      "src/util.ts",
      "typescript",
      "src/util.ts:helper:1",
    ),
  ];
}

function graphEdges(repoId: string): CodeGraphEdge[] {
  return [
    {
      id: "edge-contains-helper",
      repo_id: repoId,
      source_id: "util-file",
      target_id: "helper",
      type: "contains",
      confidence: 1,
      weight: 1,
      is_inferred: false,
      metadata: {},
    },
  ];
}

function codeChunks(repoId: string): CodeChunk[] {
  return [
    chunk(
      repoId,
      "main-chunk",
      "main-file",
      "src/main.ts",
      "export function run() {\n  return helper(41);\n}",
    ),
    chunk(
      repoId,
      "util-chunk",
      "util-file",
      "src/util.ts",
      "export function helper(x: number) {\n  return x + 1;\n}",
    ),
  ];
}

function node(
  repoId: string,
  id: string,
  type: string,
  name: string,
  filePath: string,
  language: string,
  symbolId: string,
): CodeGraphNode {
  return {
    id,
    repo_id: repoId,
    type,
    name,
    file_path: filePath,
    start_line: 1,
    end_line: 2,
    language,
    symbol_id: symbolId,
    summary: null,
    hash: `${id}-hash`,
    metadata: {},
  };
}

function chunk(
  repoId: string,
  id: string,
  nodeId: string,
  filePath: string,
  content: string,
): CodeChunk {
  return {
    id,
    repo_id: repoId,
    node_id: nodeId,
    file_path: filePath,
    start_line: 1,
    end_line: content.split(/\r?\n/).length,
    content,
    content_hash: `${id}-hash`,
    token_count: content.split(/\s+/).length,
  };
}
