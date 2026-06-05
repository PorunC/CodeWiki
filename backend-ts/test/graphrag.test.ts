import { mkdtempSync } from "node:fs";
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
    expect(trace.source_chunks.map((chunk) => chunk.file_path)).toEqual([
      "src/main.ts",
      "src/util.ts",
    ]);
    expect(
      trace.seed_nodes.some((node) => node.id === "helper" && node.hop === 0),
    ).toBe(true);
    expect(
      trace.expanded_nodes.some(
        (node) => node.id === "util-file" && node.hop === 1,
      ),
    ).toBe(true);
    expect(trace.related_edges).toEqual([
      expect.objectContaining({ id: "edge-contains-helper" }),
    ]);
    expect(trace.community_summaries).toEqual([
      expect.objectContaining({ id: "community-src" }),
    ]);
    expect(trace.community_edges).toEqual([
      expect.objectContaining({ id: "community-edge-root-src" }),
    ]);
    expect(trace.context_pack).toMatchObject({
      query: "helper",
      include_embeddings: true,
    });
    expect(trace.context).toContain("export function helper");
    expect(trace.created_at).toBeTruthy();

    const persistedTrace = store.getRetrievalTrace(repo.id, trace.trace_id);
    expect(persistedTrace?.query).toBe("helper");
    expect(persistedTrace?.chunks.map((chunk) => chunk.file_path)).toEqual([
      "src/main.ts",
      "src/util.ts",
    ]);

    const payload = retrievalTracePayload(trace);
    expect(payload).toMatchObject({
      repo_id: repo.id,
      query: "helper",
      trace_id: trace.trace_id,
      max_hops: 3,
    });
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
      metadata: { reason: "Symbol was detected in this file." },
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
      node_ids: ["main-file", "util-file", "helper"],
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
