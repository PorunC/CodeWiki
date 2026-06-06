import { mkdtempSync, writeFileSync, mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { getSettings } from "../src/config.js";
import { CodeWikiStore } from "../src/db/store.js";
import type { CodeWikiStoreApi } from "../src/db/types.js";
import { createServer } from "../src/http/server.js";
import { RepoScanner } from "../src/scanner/scanner.js";

describe("HTTP API", () => {
  let store: CodeWikiStore | null = null;

  afterEach(() => {
    store?.close();
    store = null;
  });

  it("registers, scans, analyzes, and serves graph/wiki/ask APIs", async () => {
    const root = mkdtempSync(join(tmpdir(), "codewiki-api-"));
    const repo = join(root, "repo");
    mkdirSync(repo);
    writeFileSync(join(repo, "README.md"), "# Repo\n");
    mkdirSync(join(repo, "src"));
    writeFileSync(
      join(repo, "src", "main.ts"),
      [
        "import { helper } from './util';",
        "export function run() {",
        "  return helper(41);",
        "}",
        "",
      ].join("\n"),
    );
    writeFileSync(
      join(repo, "src", "util.ts"),
      "export function helper(x: number) { return x + 1; }\n",
    );
    const settings = getSettings({
      CODEWIKI_DATABASE_URL: `sqlite:///${join(root, "codewiki.sqlite3")}`,
      CODEWIKI_STORAGE_DIR: join(root, "storage"),
    });
    store = new CodeWikiStore(settings.databasePath);
    const scanner = new TrackingScanner({ storageDir: settings.storageDir });
    const app = await createServer({ settings, store, scanner });

    const createResponse = await app.inject({
      method: "POST",
      url: "/api/repos",
      payload: { path: repo, name: "repo" },
    });
    expect(createResponse.statusCode).toBe(200);
    const created = createResponse.json<{ id: string }>();

    const reposResponse = await app.inject("/api/repos");
    expect(reposResponse.statusCode).toBe(200);
    expect(
      reposResponse
        .json<Array<{ id: string; name: string }>>()
        .map((repo) => repo.id),
    ).toEqual([created.id]);

    const filesResponse = await app.inject(`/api/repos/${created.id}/files`);
    expect(filesResponse.statusCode).toBe(200);
    expect(scanner.scannedFileRoots).toEqual([repo]);
    expect(
      filesResponse
        .json<{ files: Array<{ path: string }> }>()
        .files.map((file) => file.path),
    ).toEqual(["README.md", "src/main.ts", "src/util.ts"]);

    const analyzeResponse = await app.inject({
      method: "POST",
      url: `/api/repos/${created.id}/analyze`,
      payload: {},
    });
    expect(analyzeResponse.statusCode).toBe(200);
    const analysisPayload = analyzeResponse.json<{
      status: string;
      node_count: number;
      community_naming?: { status: string; renamed_count: number };
    }>();
    expect(analysisPayload.status).toBe("done");
    expect(analysisPayload.node_count).toBeGreaterThanOrEqual(4);
    expect(analysisPayload.community_naming).toMatchObject({
      status: "skipped",
      renamed_count: 0,
    });

    const graphResponse = await app.inject(`/api/repos/${created.id}/graph`);
    expect(graphResponse.statusCode).toBe(200);
    const graphPayload = graphResponse.json<{
      nodes: Array<{ name: string }>;
      communities: Array<{ node_ids: string[] }>;
      community_edges: Array<{ source: string; target: string; type: string }>;
    }>();
    expect(graphPayload.nodes.some((node) => node.name === "run")).toBe(true);
    expect(graphPayload.communities.length).toBeGreaterThanOrEqual(1);
    expect(Array.isArray(graphPayload.communities[0]?.node_ids)).toBe(true);
    expect(Array.isArray(graphPayload.community_edges)).toBe(true);

    const namedCommunitiesResponse = await app.inject({
      method: "POST",
      url: `/api/repos/${created.id}/communities/name`,
      payload: { max_communities: 5 },
    });
    expect(namedCommunitiesResponse.statusCode).toBe(400);
    expect(
      namedCommunitiesResponse.json<{ detail: string }>().detail,
    ).toContain("community_summary");

    const catalogResponse = await app.inject({
      method: "POST",
      url: `/api/repos/${created.id}/wiki/catalog`,
      payload: {},
    });
    expect(catalogResponse.statusCode).toBe(200);
    const catalog = catalogResponse.json<{
      title: string;
      validation_errors: string[];
      structure: { items: Array<{ slug: string }> };
    }>();
    expect(catalog.title).toBe("repo Wiki");
    expect(catalog.validation_errors).toEqual([]);
    expect(catalog.structure.items.map((item) => item.slug)).toEqual([
      "root",
      "src",
    ]);

    const wikiResponse = await app.inject({
      method: "POST",
      url: `/api/repos/${created.id}/wiki/pages/generate`,
      payload: {},
    });
    expect(wikiResponse.statusCode).toBe(200);
    expect(
      wikiResponse.json<{ page_count: number }>().page_count,
    ).toBeGreaterThanOrEqual(1);

    writeFileSync(
      join(repo, "src", "util.ts"),
      [
        "export function helper(x: number) { return x + 1; }",
        "export function double(x: number) { return x * 2; }",
        "",
      ].join("\n"),
    );
    const updateResponse = await app.inject({
      method: "POST",
      url: `/api/repos/${created.id}/update`,
      payload: { regenerate_wiki: true },
    });
    expect(updateResponse.statusCode).toBe(200);
    const updated = updateResponse.json<{
      status: string;
      mode: string;
      plan: {
        changed_files: string[];
        new_files: string[];
        deleted_files: string[];
        affected_files: string[];
        unchanged_files: string[];
      };
      wiki_regeneration: {
        status?: string;
        generated_pages?: string[];
        incremental_update?: { run_id: string };
      };
      community_naming?: { status: string; renamed_count: number };
    }>();
    expect(updated.status).toBe("done");
    expect(updated.mode).toBe("typescript_update");
    expect(updated.plan.changed_files).toEqual(["src/util.ts"]);
    expect(updated.plan.affected_files).toEqual(["src/util.ts"]);
    expect(updated.plan.new_files).toEqual([]);
    expect(updated.plan.deleted_files).toEqual([]);
    expect(updated.plan.unchanged_files).toEqual(["README.md", "src/main.ts"]);
    expect(updated.wiki_regeneration.status).toBe("updated");
    expect(
      updated.wiki_regeneration.generated_pages?.length,
    ).toBeGreaterThanOrEqual(1);
    expect(updated.community_naming).toMatchObject({
      status: "skipped",
      renamed_count: 0,
    });

    const updatedGraphResponse = await app.inject(
      `/api/repos/${created.id}/graph/search?q=double`,
    );
    expect(updatedGraphResponse.statusCode).toBe(200);
    expect(
      updatedGraphResponse
        .json<{ results: Array<{ node: { name: string } }> }>()
        .results.some((hit) => hit.node.name === "double"),
    ).toBe(true);

    const askResponse = await app.inject({
      method: "POST",
      url: `/api/repos/${created.id}/ask`,
      payload: { question: "helper", include_graph: true },
    });
    expect(askResponse.statusCode).toBe(200);
    expect(askResponse.json<{ answer: string }>().answer).toContain("helper");

    const retrieveResponse = await app.inject({
      method: "POST",
      url: `/api/repos/${created.id}/graphrag/retrieve`,
      payload: { query: "helper", max_hops: 2 },
    });
    expect(retrieveResponse.statusCode).toBe(200);
    const retrieved = retrieveResponse.json<{
      trace_id: string;
      query: string;
      source_chunks: Array<{ file_path: string }>;
      context_pack: { text?: string; chunk_count?: number };
    }>();
    expect(retrieved.trace_id).toBeTruthy();
    expect(retrieved.query).toBe("helper");
    expect(
      retrieved.source_chunks.some(
        (chunk) => chunk.file_path === "src/util.ts",
      ),
    ).toBe(true);
    expect(retrieved.context_pack.text).toContain("Query: helper");
    expect(retrieved.context_pack.chunk_count).toBeGreaterThanOrEqual(1);

    const traceResponse = await app.inject(
      `/api/repos/${created.id}/graphrag/traces/${retrieved.trace_id}`,
    );
    expect(traceResponse.statusCode).toBe(200);
    const trace = traceResponse.json<{
      trace_id: string;
      query: string;
      chunks: Array<{ file_path: string }>;
    }>();
    expect(trace.trace_id).toBe(retrieved.trace_id);
    expect(trace.query).toBe("helper");
    expect(
      trace.chunks.some((chunk) => chunk.file_path === "src/util.ts"),
    ).toBe(true);

    await app.close();
  });

  it("validates repo-scoped request bodies and missing repositories", async () => {
    const root = mkdtempSync(join(tmpdir(), "codewiki-api-ask-validation-"));
    const repo = join(root, "repo");
    mkdirSync(repo);
    writeFileSync(join(repo, "README.md"), "# Repo\n");
    const settings = getSettings({
      CODEWIKI_DATABASE_URL: `sqlite:///${join(root, "codewiki.sqlite3")}`,
      CODEWIKI_STORAGE_DIR: join(root, "storage"),
    });
    store = new CodeWikiStore(settings.databasePath);
    const app = await createServer({ settings, store });

    const createResponse = await app.inject({
      method: "POST",
      url: "/api/repos",
      payload: { path: repo, name: "repo" },
    });
    const created = createResponse.json<{ id: string }>();

    const missingQuestion = await app.inject({
      method: "POST",
      url: `/api/repos/${created.id}/ask`,
      payload: {},
    });
    expect(missingQuestion.statusCode).toBe(400);
    expect(missingQuestion.json<{ detail: string }>().detail).toBe(
      "Missing required field: question",
    );

    const blankQuestion = await app.inject({
      method: "POST",
      url: `/api/repos/${created.id}/ask`,
      payload: { question: "   " },
    });
    expect(blankQuestion.statusCode).toBe(400);
    expect(blankQuestion.json<{ detail: string }>().detail).toBe(
      "Missing required field: question",
    );

    const missingRepo = await app.inject({
      method: "POST",
      url: "/api/repos/missing-repo/ask",
      payload: { question: "helper" },
    });
    expect(missingRepo.statusCode).toBe(404);
    expect(missingRepo.json<{ detail: string }>().detail).toContain(
      "Repository not found",
    );

    const missingTranslationTarget = await app.inject({
      method: "POST",
      url: `/api/repos/${created.id}/wiki/translate`,
      payload: {},
    });
    expect(missingTranslationTarget.statusCode).toBe(400);
    expect(missingTranslationTarget.json<{ detail: string }>().detail).toBe(
      "Missing required field: target_language",
    );

    const missingTranslationRepo = await app.inject({
      method: "POST",
      url: "/api/repos/missing-repo/wiki/translate",
      payload: {},
    });
    expect(missingTranslationRepo.statusCode).toBe(404);
    expect(missingTranslationRepo.json<{ detail: string }>().detail).toContain(
      "Repository not found",
    );

    await app.close();
  });

  it("serves repository wiki data from an asynchronous store", async () => {
    const root = mkdtempSync(join(tmpdir(), "codewiki-api-async-wiki-"));
    const repoPath = join(root, "repo");
    mkdirSync(repoPath);
    const settings = getSettings({
      CODEWIKI_DATABASE_URL: `sqlite:///${join(root, "codewiki.sqlite3")}`,
      CODEWIKI_STORAGE_DIR: join(root, "storage"),
    });
    store = new CodeWikiStore(settings.databasePath);
    const repo = store.upsertRepo({
      id: "repo-async-wiki",
      name: "repo",
      path: repoPath,
      source_type: "local",
      git_url: null,
      commit_hash: null,
    });
    store.saveDocCatalog(repo.id, {
      title: "repo Wiki",
      language_code: "en",
      structure: {
        items: [
          {
            title: "Overview",
            slug: "overview",
            path: null,
            order: 0,
            kind: "page",
            topic: "Repository overview",
          },
        ],
      },
    });
    store.upsertDocPage({
      id: "page-overview",
      repo_id: repo.id,
      language_code: "en",
      slug: "overview",
      title: "Overview",
      parent_slug: null,
      markdown: "# Overview\n",
      source_refs: [],
      graph_refs: [],
      status: "generated",
      updated_at: "2026-01-01T00:00:00.000Z",
    });
    const app = await createServer({ settings, store: asyncStore(store) });

    const response = await app.inject(`/api/repos/${repo.id}/wiki`);

    expect(response.statusCode).toBe(200);
    expect(
      response.json<{
        catalog: { title: string };
        items: Array<{ slug: string }>;
        pages: Array<{ slug: string }>;
      }>(),
    ).toMatchObject({
      catalog: { title: "repo Wiki" },
      items: [{ slug: "overview" }],
      pages: [{ slug: "overview" }],
    });

    await app.close();
  });

  it("does not close an externally owned store when the server closes", async () => {
    const root = mkdtempSync(join(tmpdir(), "codewiki-api-store-"));
    const settings = getSettings({
      CODEWIKI_DATABASE_URL: `sqlite:///${join(root, "codewiki.sqlite3")}`,
      CODEWIKI_STORAGE_DIR: join(root, "storage"),
    });
    store = new CodeWikiStore(settings.databasePath);
    const app = await createServer({ settings, store });

    await app.close();

    expect(() => store?.listRepos()).not.toThrow();
  });

  it("reports LLM task routing and offline configuration checks", async () => {
    const root = mkdtempSync(join(tmpdir(), "codewiki-api-settings-"));
    const settings = getSettings({
      CODEWIKI_DATABASE_URL: `sqlite:///${join(root, "codewiki.sqlite3")}`,
      CODEWIKI_STORAGE_DIR: join(root, "storage"),
      CODEWIKI_LLM__DEFAULT__MODEL: "openai/default",
      CODEWIKI_LLM__PROFILES__PAGE__MODEL: "openai/page",
      CODEWIKI_LLM__PROFILES__PAGE__MAX_TOKENS: "777",
    });
    const app = await createServer({ settings });

    const modelsResponse = await app.inject("/api/settings/llm/models");
    expect(modelsResponse.statusCode).toBe(200);
    const models = modelsResponse.json<{
      mode: string;
      default_profile: { model: string };
      profiles: Record<
        string,
        { model: string; stream: boolean; max_tokens: number | null }
      >;
    }>();
    expect(models.mode).toBe("sdk");
    expect(models.default_profile.model).toBe("openai/default");
    expect(models.profiles.page).toMatchObject({
      model: "openai/page",
      stream: false,
      max_tokens: 777,
    });
    expect(models.profiles.qa).toMatchObject({
      model: "openai/default",
      stream: true,
    });

    const missingCredentialsResponse = await app.inject({
      method: "POST",
      url: "/api/settings/llm/test",
      payload: { task_type: "qa" },
    });
    expect(missingCredentialsResponse.statusCode).toBe(200);
    expect(
      missingCredentialsResponse.json<{
        status: string;
        configured: boolean;
        has_api_key: boolean;
      }>(),
    ).toMatchObject({
      status: "missing_credentials",
      configured: false,
      has_api_key: false,
    });

    const localModelResponse = await app.inject({
      method: "POST",
      url: "/api/settings/llm/test",
      payload: { task_type: "qa", model: "local/model" },
    });
    expect(localModelResponse.statusCode).toBe(200);
    expect(
      localModelResponse.json<{ status: string; configured: boolean }>(),
    ).toMatchObject({
      status: "configured",
      configured: true,
    });

    const unsupportedTaskResponse = await app.inject({
      method: "POST",
      url: "/api/settings/llm/test",
      payload: { task_type: "not-a-task" },
    });
    expect(unsupportedTaskResponse.statusCode).toBe(400);
    expect(unsupportedTaskResponse.json<{ detail: string }>().detail).toContain(
      "Unsupported LLM task type",
    );

    await app.close();
  });

  it("serves the configured static frontend without masking API 404s", async () => {
    const root = mkdtempSync(join(tmpdir(), "codewiki-api-static-"));
    const staticDir = join(root, "static");
    mkdirSync(staticDir);
    writeFileSync(
      join(staticDir, "index.html"),
      "<!doctype html><h1>CodeWiki shell</h1>",
    );
    const settings = getSettings({
      CODEWIKI_DATABASE_URL: `sqlite:///${join(root, "codewiki.sqlite3")}`,
      CODEWIKI_STORAGE_DIR: join(root, "storage"),
      CODEWIKI_STATIC_DIR: staticDir,
    });
    const app = await createServer({ settings });

    const rootResponse = await app.inject("/");
    expect(rootResponse.statusCode).toBe(200);
    expect(rootResponse.headers["content-type"]).toContain("text/html");
    expect(rootResponse.body).toContain("CodeWiki shell");

    const nestedFrontendResponse = await app.inject("/graph/repo");
    expect(nestedFrontendResponse.statusCode).toBe(200);
    expect(nestedFrontendResponse.body).toContain("CodeWiki shell");

    const missingApiResponse = await app.inject("/api/does-not-exist");
    expect(missingApiResponse.statusCode).toBe(404);
    expect(missingApiResponse.headers["content-type"]).toContain(
      "application/json",
    );
    expect(missingApiResponse.json<{ detail: string }>().detail).toBe(
      "Not found",
    );

    await app.close();
  });
});

function asyncStore(store: CodeWikiStore): CodeWikiStoreApi {
  return new Proxy(store, {
    get(target, property, receiver) {
      const value = Reflect.get(target, property, receiver) as unknown;
      if (typeof value !== "function") {
        return value;
      }
      return (...args: unknown[]) => Promise.resolve(value.apply(target, args));
    },
  });
}

class TrackingScanner extends RepoScanner {
  readonly scannedFileRoots: string[] = [];

  override scanFiles(
    path: string,
    options: Parameters<RepoScanner["scanFiles"]>[1] = {},
  ): ReturnType<RepoScanner["scanFiles"]> {
    this.scannedFileRoots.push(path);
    return super.scanFiles(path, options);
  }
}
