import { mkdtempSync } from "node:fs";
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
        file_path: "src/main.ts",
        start_line: 1,
      }),
      expect.objectContaining({
        citation_id: "S2",
        file_path: "src/util.ts",
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
    expect(result.catalog.structure.items).toEqual([
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
    ]);
    expect(llm.operations[0]?.inputPayload.repo_name).toBe("Demo Repo");

    const pages = await service.generateAllPagesWithLlmFallback(repo.id);

    expect(pages.map((page) => page.page.slug)).toEqual(["runtime-flow"]);
    expect(pages[0]?.page.title).toBe("Runtime Flow");
    expect(pages[0]?.page.markdown).toContain(
      "`helper` (function) in `src/util.ts`",
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
});

class FakeWikiLlm {
  readonly operations: LlmOperation[] = [];

  constructor(
    private readonly completions: Record<string, JsonObject | string>,
  ) {}

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
    const content =
      typeof completion === "string" ? completion : JSON.stringify(completion);
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
