import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { getSettings } from "../src/config.js";
import { CodeWikiStore } from "../src/db/store.js";
import { CodeWikiMCPServer } from "../src/mcp/server.js";
import { RepoScanner } from "../src/scanner/scanner.js";
import type { JsonObject } from "../src/types.js";
import { CODEWIKI_VERSION } from "../src/version.js";

describe("CodeWiki MCP server", () => {
  let store: CodeWikiStore | null = null;

  afterEach(() => {
    store?.close();
    store = null;
  });

  it("initializes, lists tools, and runs repository analysis tools", async () => {
    const root = mkdtempSync(join(tmpdir(), "codewiki-mcp-"));
    const repo = join(root, "repo");
    mkdirSync(join(repo, "src"), { recursive: true });
    writeFileSync(join(repo, "README.md"), "# MCP Repo\n");
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
    const scanner = new RepoScanner({ storageDir: settings.storageDir });
    const server = new CodeWikiMCPServer({ settings, store, scanner });
    expect(server.scanner).toBe(scanner);

    const initialized = await server.handleMessage({
      jsonrpc: "2.0",
      id: 1,
      method: "initialize",
      params: { protocolVersion: "2024-11-05" },
    });
    expect(asRecord(asRecord(initialized).result).serverInfo).toMatchObject({
      name: "codewiki",
      version: CODEWIKI_VERSION,
    });

    const listed = await server.handleMessage({
      jsonrpc: "2.0",
      id: 2,
      method: "tools/list",
    });
    const toolNames = asArray(asRecord(asRecord(listed).result).tools).map(
      (tool) => asRecord(tool).name,
    );
    expect(toolNames).toEqual(
      expect.arrayContaining([
        "codewiki_repo_add",
        "codewiki_analyze",
        "codewiki_wiki_pages_generate",
        "codewiki_wiki_catalog_evidence",
        "codewiki_wiki_catalog_save",
        "codewiki_wiki_catalog_validate",
        "codewiki_wiki_plan",
        "codewiki_wiki_evidence",
        "codewiki_wiki_page_save",
        "codewiki_wiki_page_validate",
        "codewiki_llm_models",
        "codewiki_graph_explore",
        "codewiki_trace",
        "codewiki_graph_node_read",
        "codewiki_communities_list",
        "codewiki_communities_name",
      ]),
    );

    const added = await callTool<{ id: string; name: string }>(
      server,
      "codewiki_repo_add",
      {
        path: repo,
        name: "repo",
      },
    );
    expect(added.name).toBe("repo");

    const analyzed = await callTool<{ status: string; node_count: number }>(
      server,
      "codewiki_analyze",
      {
        repo: added.id,
      },
    );
    expect(analyzed.status).toBe("done");
    expect(analyzed.node_count).toBeGreaterThanOrEqual(4);

    const search = await callTool<{
      results: Array<{ node: { id: string; name: string } }>;
    }>(server, "codewiki_graph_search", {
      repo: added.id,
      query: "helper",
    });
    expect(search.results.some((hit) => hit.node.name === "helper")).toBe(true);
    const helperNode = search.results.find(
      (hit) => hit.node.name === "helper",
    )?.node;
    expect(helperNode).toBeTruthy();

    const models = await callTool<{
      mode: string;
      default_profile: { has_api_key: boolean };
    }>(server, "codewiki_llm_models", {});
    expect(models.mode).toBe("sdk");
    expect(models.default_profile.has_api_key).toBe(false);

    const explored = await callTool<{
      query: string;
      entry_points: Array<{ name: string }>;
    }>(server, "codewiki_graph_explore", {
      repo: added.id,
      query: "helper",
      max_files: 2,
      max_nodes: 8,
    });
    expect(explored.query).toBe("helper");
    expect(explored.entry_points.some((node) => node.name === "helper")).toBe(
      true,
    );

    const traced = await callTool<{
      found: boolean;
      nodes: Array<{ name: string }>;
    }>(server, "codewiki_trace", {
      repo: added.id,
      from_symbol: "run",
      to_symbol: "helper",
    });
    expect(traced.found).toBe(true);
    expect(traced.nodes.map((node) => node.name)).toEqual(
      expect.arrayContaining(["run", "helper"]),
    );

    const nodeRead = await callTool<{
      node: { id: string; name: string };
      adjacent_edges: unknown[];
    }>(server, "codewiki_graph_node_read", {
      repo: added.id,
      node_id: helperNode!.id,
    });
    expect(nodeRead.node.name).toBe("helper");
    expect(nodeRead.adjacent_edges.length).toBeGreaterThanOrEqual(1);

    const communities = await callTool<Array<{ id: string; name: string }>>(
      server,
      "codewiki_communities_list",
      { repo: added.id },
    );
    expect(communities.length).toBeGreaterThanOrEqual(1);

    const namedCommunities = await callToolError(
      server,
      "codewiki_communities_name",
      {
        repo: added.id,
        max_communities: 5,
      },
    );
    expect(namedCommunities.error).toContain("community_summary");

    const catalogError = await callToolError(
      server,
      "codewiki_wiki_catalog_generate",
      {
        repo: added.id,
      },
    );
    expect(catalogError.error).toContain(
      "LLM catalog profile is not configured",
    );

    const catalogEvidence = await callTool<{
      repo_id: string;
      prompt_version: string;
      catalog_evidence: { module_candidates: Array<{ path: string }> };
    }>(server, "codewiki_wiki_catalog_evidence", {
      repo: added.id,
    });
    expect(catalogEvidence.repo_id).toBe(added.id);
    expect(catalogEvidence.prompt_version).toBe("catalog:deepwiki:v4");
    expect(
      catalogEvidence.catalog_evidence.module_candidates.some(
        (candidate) => candidate.path === "src",
      ),
    ).toBe(true);

    const emptyAgentPlan = await callTool<{
      status: string;
      pages: Array<{ slug: string; title: string }>;
    }>(server, "codewiki_wiki_plan", { repo: added.id });
    expect(emptyAgentPlan.status).toBe("catalog_required");
    expect(emptyAgentPlan.pages).toEqual([]);

    const savedCatalog = await callTool<{
      status: string;
      validation_errors: string[];
    }>(server, "codewiki_wiki_catalog_save", {
      repo: added.id,
      catalog: agentCatalogObject("repo Wiki"),
    });
    expect(savedCatalog.status).toBe("saved");
    expect(savedCatalog.validation_errors).toEqual([]);

    const catalogValidation = await callTool<{
      status: string;
      validation_errors: string[];
    }>(server, "codewiki_wiki_catalog_validate", { repo: added.id });
    expect(catalogValidation.status).toBe("valid");
    expect(catalogValidation.validation_errors).toEqual([]);

    const agentPlan = await callTool<{
      status: string;
      pages: Array<{ slug: string; title: string }>;
    }>(server, "codewiki_wiki_plan", { repo: added.id });
    expect(agentPlan.status).toBe("planned");
    expect(agentPlan.pages.map((page) => page.slug)).toEqual([
      "overview",
      "architecture",
      "reading-guide",
      "dependencies",
      "src",
    ]);

    const agentEvidence = await callTool<{
      allowed_source_refs: Array<{ citation_id: string; file_path: string }>;
    }>(server, "codewiki_wiki_evidence", {
      repo: added.id,
      slug: "src",
    });
    expect(
      agentEvidence.allowed_source_refs.some(
        (ref) => ref.citation_id === "S1" && ref.file_path.startsWith("src/"),
      ),
    ).toBe(true);

    const agentSaved = await callTool<{
      status: string;
      validation_errors: string[];
      page: { slug: string; source_refs: Array<{ citation_id: string }> };
    }>(server, "codewiki_wiki_page_save", {
      repo: added.id,
      slug: "src",
      title: "Src",
      markdown:
        "# Src\n\nThe source directory contains TypeScript runtime code and utilities. [[S1]]",
    });
    expect(agentSaved.status).toBe("generated");
    expect(agentSaved.validation_errors).toEqual([]);
    expect(agentSaved.page.source_refs).toEqual([
      expect.objectContaining({ citation_id: "S1" }),
    ]);

    const agentValidation = await callTool<{
      status: string;
      validation_errors: string[];
    }>(server, "codewiki_wiki_page_validate", {
      repo: added.id,
      slug: "src",
    });
    expect(agentValidation.status).toBe("valid");
    expect(agentValidation.validation_errors).toEqual([]);

    const wiki = await callTool<{ page_count: number }>(
      server,
      "codewiki_wiki_pages_generate",
      {
        repo: added.id,
      },
    );
    expect(wiki.page_count).toBeGreaterThanOrEqual(1);

    writeFileSync(
      join(repo, "src", "util.ts"),
      [
        "export function helper(x: number) { return x + 1; }",
        "export function double(x: number) { return x * 2; }",
        "",
      ].join("\n"),
    );
    const updated = await callTool<{
      status: string;
      mode: string;
      plan: { changed_files: string[]; affected_files: string[] };
      wiki_regeneration: { status?: string; generated_pages?: string[] };
    }>(server, "codewiki_update", {
      repo: added.id,
      regenerate_wiki: true,
    });
    expect(updated.status).toBe("done");
    expect(updated.mode).toBe("typescript_update");
    expect(updated.plan.changed_files).toEqual(["src/util.ts"]);
    expect(updated.plan.affected_files).toEqual(["src/util.ts"]);
    expect(updated.wiki_regeneration.status).toBe("updated");
    expect(
      updated.wiki_regeneration.generated_pages?.length,
    ).toBeGreaterThanOrEqual(1);

    const updatedSearch = await callTool<{
      results: Array<{ node: { name: string } }>;
    }>(server, "codewiki_graph_search", {
      repo: added.id,
      query: "double",
    });
    expect(
      updatedSearch.results.some((hit) => hit.node.name === "double"),
    ).toBe(true);

    const retrieval = await callTool<{
      trace_id: string;
      query: string;
      source_chunks: Array<{ file_path: string }>;
      context_pack: { text?: string; chunk_count?: number };
    }>(server, "codewiki_retrieve_context", {
      repo: added.id,
      query: "helper",
    });
    expect(retrieval.trace_id).toBeTruthy();
    expect(retrieval.query).toBe("helper");
    expect(
      retrieval.source_chunks.some(
        (chunk) => chunk.file_path === "src/util.ts",
      ),
    ).toBe(true);
    expect(retrieval.context_pack.text).toContain("Query: helper");
    expect(retrieval.context_pack.chunk_count).toBeGreaterThanOrEqual(1);
    const persistedTrace = store?.getRetrievalTrace(
      added.id,
      retrieval.trace_id,
    );
    expect(persistedTrace?.query).toBe("helper");
    expect(
      persistedTrace?.chunks.some((chunk) => chunk.file_path === "src/util.ts"),
    ).toBe(true);
  });
});

let requestId = 10;

async function callTool<T>(
  server: CodeWikiMCPServer,
  name: string,
  args: JsonObject,
): Promise<T> {
  const response = await server.handleMessage({
    jsonrpc: "2.0",
    id: requestId++,
    method: "tools/call",
    params: { name, arguments: args },
  });
  const result = asRecord(asRecord(response).result);
  expect(result.isError).toBe(false);
  const content = asArray(result.content);
  const text = asRecord(content[0]).text;
  expect(typeof text).toBe("string");
  return JSON.parse(text as string) as T;
}

async function callToolError(
  server: CodeWikiMCPServer,
  name: string,
  args: JsonObject,
): Promise<{ error: string }> {
  const response = await server.handleMessage({
    jsonrpc: "2.0",
    id: requestId++,
    method: "tools/call",
    params: { name, arguments: args },
  });
  const result = asRecord(asRecord(response).result);
  expect(result.isError).toBe(true);
  const content = asArray(result.content);
  const text = asRecord(content[0]).text;
  expect(typeof text).toBe("string");
  return JSON.parse(text as string) as { error: string };
}

function agentCatalogObject(title: string): JsonObject {
  return {
    title,
    items: [
      {
        title: "Overview",
        slug: "overview",
        path: "overview",
        order: 0,
        kind: "page",
        topic: "repository overview",
        source_hints: ["README.md"],
      },
      {
        title: "Architecture",
        slug: "architecture",
        path: "architecture",
        order: 1,
        kind: "page",
        topic: "runtime architecture",
        source_hints: ["src/main.ts", "src/util.ts"],
      },
      {
        title: "Reading Guide",
        slug: "reading-guide",
        path: "reading-guide",
        order: 2,
        kind: "page",
        topic: "recommended reading order",
        source_hints: ["README.md"],
      },
      {
        title: "Dependencies",
        slug: "dependencies",
        path: "dependencies",
        order: 3,
        kind: "page",
        topic: "imports and dependencies",
        source_hints: ["src/main.ts", "src/util.ts"],
      },
      {
        title: "Src",
        slug: "src",
        path: "src",
        order: 4,
        kind: "page",
        topic: "TypeScript source files",
        source_hints: ["src/main.ts", "src/util.ts"],
      },
    ],
  };
}

function asRecord(value: unknown): Record<string, unknown> {
  expect(value).toBeTruthy();
  expect(typeof value).toBe("object");
  expect(Array.isArray(value)).toBe(false);
  return value as Record<string, unknown>;
}

function asArray(value: unknown): unknown[] {
  expect(Array.isArray(value)).toBe(true);
  return value as unknown[];
}
