import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { CommunityNamingService } from "../src/graph/communityNamingService.js";
import { CodeWikiStore } from "../src/db/store.js";
import type { CachedLlmCompletion, LlmOperation } from "../src/llm/cache.js";
import type {
  CodeChunk,
  CodeGraphEdge,
  CodeGraphNode,
  GraphCommunity,
  GraphCommunityEdge,
  JsonObject,
  LlmRun,
  RepoDescriptor,
} from "../src/types.js";

describe("CommunityNamingService", () => {
  let store: CodeWikiStore | null = null;

  afterEach(() => {
    store?.close();
    store = null;
  });

  it("returns no_communities before checking LLM configuration", async () => {
    const root = mkdtempSync(join(tmpdir(), "codewiki-community-empty-"));
    store = new CodeWikiStore(join(root, "codewiki.sqlite3"));
    const repo = store.upsertRepo(repoDescriptor(root));
    store.replaceGraph(repo.id, {
      nodes: [],
      edges: [],
      chunks: [],
    });
    const service = new CommunityNamingService(store, new FakeCommunityLlm({}));

    const result = await service.nameCommunities(repo.id, {
      maxCommunities: 5,
    });

    expect(result).toMatchObject({
      repo_id: repo.id,
      status: "no_communities",
      renamed_count: 0,
      community_count: 0,
      max_communities: 5,
      named_community_ids: [],
      errors: [],
      communities: [],
    });
  });

  it("skips analysis-triggered naming when community summary LLM is not configured", async () => {
    const root = mkdtempSync(join(tmpdir(), "codewiki-community-skipped-"));
    store = new CodeWikiStore(join(root, "codewiki.sqlite3"));
    const repo = store.upsertRepo(repoDescriptor(root));
    seedGraph(store, repo.id);
    const service = new CommunityNamingService(store, new FakeCommunityLlm({}));

    const result = await service.nameCommunitiesForAnalysis(repo.id, {
      maxCommunities: 5,
    });

    expect(result).toMatchObject({
      repo_id: repo.id,
      status: "skipped",
      renamed_count: 0,
      community_count: 2,
      max_communities: 5,
      named_community_ids: [],
      errors: [
        "LLM community naming skipped because no LLM endpoint or API key is configured.",
      ],
      communities: [],
    });
    expect(namesById(store.listGraphCommunities(repo.id))).toEqual({
      "community-root": "root",
      "community-src": "src",
    });
  });

  it("uses provider-backed names and summaries when configured", async () => {
    const root = mkdtempSync(join(tmpdir(), "codewiki-community-llm-"));
    store = new CodeWikiStore(join(root, "codewiki.sqlite3"));
    const repo = store.upsertRepo(repoDescriptor(root));
    seedGraph(store, repo.id);
    const llm = new FakeCommunityLlm({
      community_summary: {
        communities: [
          {
            id: "community-src",
            name: "Runtime Helpers",
            summary:
              "Runtime Helpers covers the source files that call and define helper.",
          },
          {
            id: "community-root",
            name: "Project Documentation",
            summary:
              "Project Documentation covers README guidance for the repository.",
          },
        ],
      },
    });
    const service = new CommunityNamingService(store, llm);

    const result = await service.nameCommunities(repo.id, {
      maxCommunities: 5,
    });

    expect(result.status).toBe("renamed");
    expect(result.renamed_count).toBe(2);
    expect(result.errors).toEqual([]);
    expect(result.llm).toMatchObject({
      status: "success",
      model: "fake/community_summary",
      cache_hit: false,
    });
    expect(result.communities).toEqual([
      expect.objectContaining({
        id: "community-src",
        name: "Runtime Helpers",
      }),
      expect.objectContaining({
        id: "community-root",
        name: "Project Documentation",
      }),
    ]);
    expect(store.getRetrievalTrace(repo.id, "missing")).toBeNull();
    const storedCommunities = store.listGraphCommunities(repo.id);
    expect(namesById(storedCommunities)).toEqual({
      "community-root": "Project Documentation",
      "community-src": "Runtime Helpers",
    });
    expect(
      storedCommunities.every(
        (community) =>
          typeof community.summary_hash === "string" &&
          community.summary_hash.length > 0,
      ),
    ).toBe(true);
    expect(store.listGraphCommunityEdges(repo.id)).toEqual([]);
    expect(llm.operations[0]?.inputPayload.communities).toEqual([
      expect.objectContaining({
        id: "community-src",
        files: ["src/main.ts", "src/util.ts"],
      }),
      expect.objectContaining({
        id: "community-root",
        files: ["README.md"],
      }),
    ]);
  });

  it("reports partial results when provider JSON is invalid", async () => {
    const root = mkdtempSync(join(tmpdir(), "codewiki-community-fallback-"));
    store = new CodeWikiStore(join(root, "codewiki.sqlite3"));
    const repo = store.upsertRepo(repoDescriptor(root));
    seedGraph(store, repo.id);
    const service = new CommunityNamingService(
      store,
      new FakeCommunityLlm({ community_summary: "not json" }),
    );

    const result = await service.nameCommunities(repo.id, {
      maxCommunities: 5,
    });

    expect(result.status).toBe("partial");
    expect(result.llm).toMatchObject({
      status: "partial",
    });
    expect(result.errors).toEqual([
      "batch 1: LLM did not return a JSON object.",
    ]);
    expect(namesById(result.communities)).toEqual({
      "community-root": "root",
      "community-src": "src",
    });
    expect(namesById(store.listGraphCommunities(repo.id))).toEqual({
      "community-root": "root",
      "community-src": "src",
    });
  });

  it("uses deterministic fallback names when provider names are generic", async () => {
    const root = mkdtempSync(join(tmpdir(), "codewiki-community-generic-"));
    store = new CodeWikiStore(join(root, "codewiki.sqlite3"));
    const repo = store.upsertRepo(repoDescriptor(root));
    seedGraph(store, repo.id);
    const service = new CommunityNamingService(
      store,
      new FakeCommunityLlm({
        community_summary: {
          communities: [
            {
              id: "community-src",
              name: "backend subsystem",
              summary: "Source helpers.",
            },
            {
              id: "community-root",
              name: "Cluster 23",
              summary: "Repository documentation.",
            },
          ],
        },
      }),
    );

    const result = await service.nameCommunities(repo.id, {
      maxCommunities: 5,
    });

    expect(result.status).toBe("renamed");
    expect(result.llm).toMatchObject({ status: "success" });
    expect(namesById(result.communities)).toEqual({
      "community-root": "README",
      "community-src": "Util",
    });
  });

  it("orders child naming targets by node id prefix file count like main", async () => {
    const root = mkdtempSync(join(tmpdir(), "codewiki-community-targets-"));
    store = new CodeWikiStore(join(root, "codewiki.sqlite3"));
    const repo = store.upsertRepo(repoDescriptor(root));
    store.replaceGraph(repo.id, {
      nodes: hierarchyTargetNodes(repo.id),
      edges: [],
      chunks: [],
    });
    store.replaceGraphCommunities(repo.id, [
      community(repo.id, "parent", {
        level: 0,
        rank: 0,
        nodeIds: ["parent:node"],
      }),
      community(repo.id, "wide-by-node-id", {
        level: 1,
        parentId: "parent",
        rank: 1,
        nodeIds: ["src/a.ts:one", "src/b.ts:two"],
      }),
      community(repo.id, "wide-by-file-path", {
        level: 1,
        parentId: "parent",
        rank: 0,
        nodeIds: ["same-prefix:one", "same-prefix:two"],
      }),
    ]);
    const llm = new FakeCommunityLlm({
      community_summary: {
        communities: [
          {
            id: "parent",
            name: "Parent Area",
            summary: "Parent area.",
          },
          {
            id: "wide-by-node-id",
            name: "Node Prefix Area",
            summary: "Node id prefixes drive target selection.",
          },
        ],
      },
    });
    const service = new CommunityNamingService(store, llm);

    const result = await service.nameCommunities(repo.id, {
      maxCommunities: 2,
    });

    expect(result.named_community_ids).toEqual(["parent", "wide-by-node-id"]);
    const requestedCommunities = llm.operations[0]?.inputPayload.communities;
    expect(Array.isArray(requestedCommunities)).toBe(true);
    expect(
      (Array.isArray(requestedCommunities) ? requestedCommunities : []).map(
        (item) =>
          typeof item === "object" && item !== null && "id" in item
            ? item.id
            : null,
      ),
    ).toEqual(["parent", "wide-by-node-id"]);
  });
});

class FakeCommunityLlm {
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

function seedGraph(store: CodeWikiStore, repoId: string): void {
  store.replaceGraph(repoId, {
    nodes: graphNodes(repoId),
    edges: graphEdges(repoId),
    chunks: codeChunks(repoId),
  });
  store.replaceGraphCommunities(repoId, graphCommunities(repoId));
  store.replaceGraphCommunityEdges(repoId, graphCommunityEdges(repoId));
}

function namesById(
  communities: Array<{ id: string; name: string }>,
): Record<string, string> {
  return Object.fromEntries(
    communities.map((community) => [community.id, community.name]),
  );
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

function hierarchyTargetNodes(repoId: string): CodeGraphNode[] {
  return [
    node(
      repoId,
      "parent:node",
      "function",
      "parent",
      "parent.ts",
      "typescript",
      "parent.ts:parent:1",
    ),
    node(
      repoId,
      "src/a.ts:one",
      "function",
      "one",
      "shared.ts",
      "typescript",
      "src/a.ts:one",
    ),
    node(
      repoId,
      "src/b.ts:two",
      "function",
      "two",
      "shared.ts",
      "typescript",
      "src/b.ts:two",
    ),
    node(
      repoId,
      "same-prefix:one",
      "function",
      "sameOne",
      "wide/one.ts",
      "typescript",
      "same-prefix:one",
    ),
    node(
      repoId,
      "same-prefix:two",
      "function",
      "sameTwo",
      "wide/two.ts",
      "typescript",
      "same-prefix:two",
    ),
  ];
}

function community(
  repoId: string,
  id: string,
  options: {
    level: number;
    rank: number;
    nodeIds: string[];
    parentId?: string | null | undefined;
  },
): GraphCommunity {
  return {
    id,
    repo_id: repoId,
    name: id,
    level: options.level,
    parent_id: options.parentId ?? null,
    rank: options.rank,
    node_ids: options.nodeIds,
    summary: `${id} summary.`,
    summary_hash: `${id}-hash`,
    created_at: "2026-01-01T00:00:00.000Z",
  };
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
