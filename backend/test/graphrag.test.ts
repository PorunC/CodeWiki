import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { CodeWikiStore } from "../src/db/store.js";
import { GraphRAGService } from "../src/graphrag/graphragService.js";
import { retrievalTracePayload } from "../src/graphrag/payloads.js";
import type {
  CodeChunk,
  CodeGraphEdge,
  CodeGraphNode,
  GraphCommunity,
  GraphCommunityEdge,
  RepoDescriptor,
} from "../src/types.js";

describe("GraphRAGService", () => {
  let store: CodeWikiStore | null = null;

  afterEach(() => {
    store?.close();
    store = null;
  });

  it("builds, retrieves, expands graph context, and persists traces", async () => {
    const root = mkdtempSync(join(tmpdir(), "codewiki-graphrag-"));
    writeGraphSourceFiles(root);
    store = new CodeWikiStore(join(root, "codewiki.sqlite3"));
    const repo = store.upsertRepo(repoDescriptor(root));
    store.replaceGraph(repo.id, {
      nodes: graphNodes(repo.id),
      edges: graphEdges(repo.id),
      chunks: codeChunks(repo.id),
    });
    store.replaceGraphCommunities(repo.id, graphCommunities(repo.id));
    store.replaceGraphCommunityEdges(repo.id, graphCommunityEdges(repo.id));

    const service = new GraphRAGService(store);
    expect(
      await service.buildIndex(repo.id, { includeEmbeddings: true }),
    ).toMatchObject({
      repo_id: repo.id,
      status: "built",
      chunk_count: 2,
      embedding_count: 0,
      include_embeddings: true,
    });

    const trace = await service.retrieve(repo.id, " helper ", {
      includeEmbeddings: true,
      maxHops: 3,
      limit: 2,
    });
    expect(trace.query).toBe("helper");
    expect(trace.max_hops).toBe(3);
    expect(trace.source_chunks.map((chunk) => chunk.file_path)).toEqual(
      expect.arrayContaining(["src/util.ts", "src/main.ts"]),
    );
    expect(
      trace.seed_nodes.some((node) => node.id === "helper" && node.hop === 0),
    ).toBe(true);
    expect(
      [...trace.seed_nodes, ...trace.expanded_nodes].some(
        (node) => node.id === "util-file",
      ),
    ).toBe(true);
    expect(trace.related_edges).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ id: "edge-contains-helper" }),
      ]),
    );
    expect(trace.community_summaries).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ id: "community-src" }),
      ]),
    );
    expect(trace.community_edges).toEqual([]);
    expect(trace.context_pack).toMatchObject({
      chunk_count: 2,
      community_count: 2,
    });
    expect(trace.context_pack.source_chunk_ids).toHaveLength(2);
    expect(trace.context_pack.text).toContain("Query: helper");
    expect(trace.context).toContain("export function helper");
    expect(trace.created_at).toBeTruthy();

    const persistedTrace = store.getRetrievalTrace(repo.id, trace.trace_id);
    expect(persistedTrace?.query).toBe("helper");
    expect(persistedTrace?.chunks.map((chunk) => chunk.file_path)).toEqual(
      expect.arrayContaining(["src/util.ts", "src/main.ts"]),
    );

    const payload = retrievalTracePayload(trace);
    expect(payload).toMatchObject({
      repo_id: repo.id,
      query: "helper",
      trace_id: trace.trace_id,
      max_hops: 3,
    });
  });

  it("lazily rebuilds source chunks when retrieval starts from graph-only data", async () => {
    const root = mkdtempSync(join(tmpdir(), "codewiki-graphrag-lazy-"));
    writeGraphSourceFiles(root);
    store = new CodeWikiStore(join(root, "codewiki.sqlite3"));
    const repo = store.upsertRepo(repoDescriptor(root));
    store.replaceGraph(repo.id, {
      nodes: graphNodes(repo.id),
      edges: graphEdges(repo.id),
      chunks: [],
    });
    store.replaceGraphCommunities(repo.id, graphCommunities(repo.id));
    store.replaceGraphCommunityEdges(repo.id, graphCommunityEdges(repo.id));

    const trace = await new GraphRAGService(store).retrieve(
      repo.id,
      "run helper",
      { maxHops: 2 },
    );

    expect(store.listCodeChunks(repo.id).length).toBeGreaterThanOrEqual(2);
    expect(trace.source_chunks.length).toBeGreaterThanOrEqual(1);
    expect(
      trace.source_chunks.some(
        (chunk) =>
          typeof chunk.content === "string" &&
          chunk.content.includes("export function helper"),
      ),
    ).toBe(true);
    expect(trace.context_pack.text).toContain("Community Summaries:");
    expect(trace.context_pack.chunk_count).toBe(trace.source_chunks.length);
    expect(trace.context_pack.community_count).toBe(
      trace.community_summaries.length,
    );
    expect(trace.context_pack.text).toContain("Graph Facts:");
    expect(
      trace.source_chunks.every((chunk) => {
        const components = chunk.score_components;
        return (
          components &&
          typeof components === "object" &&
          [
            "semantic_score",
            "keyword_score",
            "graph_proximity_score",
            "node_importance_score",
            "source_freshness_score",
          ].every((key) => key in components)
        );
      }),
    ).toBe(true);
  });
});

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
      "run",
      "function",
      "run",
      "src/main.ts",
      "typescript",
      "src/main.ts:run:1",
      1,
      3,
    ),
    node(
      repoId,
      "helper",
      "function",
      "helper",
      "src/util.ts",
      "typescript",
      "src/util.ts:helper:1",
      1,
      3,
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
      metadata: { reason: "Symbol was detected in this file." },
    },
    {
      id: "edge-contains-run",
      repo_id: repoId,
      source_id: "main-file",
      target_id: "run",
      type: "contains",
      confidence: 1,
      weight: 1,
      is_inferred: false,
      metadata: { reason: "Symbol was detected in this file." },
    },
    {
      id: "edge-run-helper",
      repo_id: repoId,
      source_id: "run",
      target_id: "helper",
      type: "calls",
      confidence: 1,
      weight: 1,
      is_inferred: false,
      metadata: { reason: "run calls helper." },
    },
  ];
}

function graphCommunities(repoId: string): GraphCommunity[] {
  return [
    {
      id: "community-src",
      repo_id: repoId,
      name: "src",
      level: 0,
      parent_id: null,
      rank: 0,
      node_ids: ["main-file", "util-file", "run", "helper"],
      summary: "Source files.",
      summary_hash: "community-src-hash",
      created_at: "2026-01-01T00:00:00.000Z",
    },
    {
      id: "community-root",
      repo_id: repoId,
      name: "root",
      level: 0,
      parent_id: null,
      rank: 1,
      node_ids: ["readme"],
      summary: "Root files.",
      summary_hash: "community-root-hash",
      created_at: "2026-01-01T00:00:00.000Z",
    },
  ];
}

function graphCommunityEdges(repoId: string): GraphCommunityEdge[] {
  return [
    {
      id: "community-edge-root-src",
      repo_id: repoId,
      source_community_id: "community-root",
      target_community_id: "community-src",
      type: "related",
      weight: 1,
      confidence: 0.8,
      reason: "Root documentation references source.",
      evidence_edge_ids: ["edge-contains-helper"],
      created_at: "2026-01-01T00:00:00.000Z",
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
  startLine = 1,
  endLine = 2,
): CodeGraphNode {
  return {
    id,
    repo_id: repoId,
    type,
    name,
    file_path: filePath,
    start_line: startLine,
    end_line: endLine,
    language,
    symbol_id: symbolId,
    summary: null,
    hash: `${id}-hash`,
    metadata: {},
  };
}

function writeGraphSourceFiles(root: string): void {
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
