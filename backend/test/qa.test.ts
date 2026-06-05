import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { CodeWikiStore } from "../src/db/store.js";
import { CachedLlmService } from "../src/llm/cache.js";
import type {
  LlmCompletionOptions,
  LlmCompletionResult,
  LlmGateway,
  LlmMessage,
} from "../src/llm/gateway.js";
import type { ResolvedLlmProfile } from "../src/llm/modelRouter.js";
import { QuestionAnswerer } from "../src/qa/questionAnswerer.js";
import type {
  CodeChunk,
  CodeGraphEdge,
  CodeGraphNode,
  RepoDescriptor,
} from "../src/types.js";

describe("QuestionAnswerer LLM integration", () => {
  let store: CodeWikiStore | null = null;

  afterEach(() => {
    store?.close();
    store = null;
  });

  it("uses a configured provider answer and reuses cached completions", async () => {
    const context = createIndexedRepo();
    store = context.store;
    const gateway = new FakeGateway({
      content:
        "The helper function increments the input and is used by run. [S1]",
    });
    const questionAnswerer = new QuestionAnswerer(
      store,
      new CachedLlmService(store, gateway),
    );

    const first = await questionAnswerer.answerWithLlmFallback(
      context.repo.id,
      {
        question: "How is helper used?",
        include_graph: true,
      },
    );

    expect(first.answer).toBe(
      "The helper function increments the input and is used by run. [S1]",
    );
    expect(first.llm).toMatchObject({
      status: "success",
      cache_hit: false,
      model: "openai/test-model",
      provider: "openai",
    });
    expect(gateway.calls).toHaveLength(1);
    expect(gateway.calls[0]?.messages.at(-1)?.content).toContain(
      "export function helper",
    );

    const second = await questionAnswerer.answerWithLlmFallback(
      context.repo.id,
      {
        question: "How is helper used?",
        include_graph: true,
      },
    );

    expect(second.answer).toBe(first.answer);
    expect(second.llm).toMatchObject({
      status: "success",
      cache_hit: true,
    });
    expect(gateway.calls).toHaveLength(1);

    const runs = store.listLlmRuns(context.repo.id, { taskType: "qa" });
    expect(runs).toHaveLength(2);
    expect(runs[0]).toMatchObject({ cached: true, status: "success" });
    expect(runs[1]).toMatchObject({ cached: false, status: "success" });
  });

  it("falls back to the local answer and records sanitized provider failures", async () => {
    const context = createIndexedRepo();
    store = context.store;
    const gateway = new FakeGateway({
      error: new Error("provider failed with api_key=sk-secret-token-value"),
    });
    const questionAnswerer = new QuestionAnswerer(
      store,
      new CachedLlmService(store, gateway),
    );

    const response = await questionAnswerer.answerWithLlmFallback(
      context.repo.id,
      {
        question: "helper",
      },
    );

    expect(String(response.answer)).toContain(
      "I found 2 relevant source sections",
    );
    expect(response.llm).toMatchObject({
      status: "fallback",
    });
    expect(JSON.stringify(response.llm)).not.toContain("sk-secret");
    const runs = store.listLlmRuns(context.repo.id, { taskType: "qa" });
    expect(runs).toHaveLength(1);
    expect(runs[0]).toMatchObject({
      status: "error",
      model: "openai/test-model",
    });
    expect(runs[0]?.error).toContain("api_key=[REDACTED]");
  });
});

class FakeGateway implements LlmGateway {
  readonly calls: Array<{
    taskType: string;
    messages: LlmMessage[];
    options: LlmCompletionOptions;
  }> = [];

  constructor(
    private readonly options: {
      content?: string | undefined;
      error?: Error | undefined;
    } = {},
  ) {}

  isConfigured(): boolean {
    return true;
  }

  profile(taskType: string): ResolvedLlmProfile {
    return {
      task_type: taskType,
      model: "openai/test-model",
      provider_type: "openai",
      endpoint: null,
      api_key: "test-key",
      max_tokens: null,
      stream: false,
    };
  }

  async complete(
    taskType: string,
    messages: LlmMessage[],
    options: LlmCompletionOptions = {},
  ): Promise<LlmCompletionResult> {
    this.calls.push({ taskType, messages, options });
    if (this.options.error) {
      throw this.options.error;
    }
    return {
      content: this.options.content ?? "Provider answer [S1]",
      model: "openai/test-model",
      provider: "openai",
      usage: {
        prompt_tokens: 12,
        completion_tokens: 8,
      },
    };
  }
}

function createIndexedRepo(): { store: CodeWikiStore; repo: RepoDescriptor } {
  const root = mkdtempSync(join(tmpdir(), "codewiki-qa-"));
  const store = new CodeWikiStore(join(root, "codewiki.sqlite3"));
  const repo = store.upsertRepo({
    id: "repo-1",
    name: "Demo Repo",
    path: root,
    source_type: "local",
    git_url: null,
    commit_hash: null,
  });
  store.replaceGraph(repo.id, {
    nodes: graphNodes(repo.id),
    edges: graphEdges(repo.id),
    chunks: codeChunks(repo.id),
  });
  return { store, repo };
}

function graphNodes(repoId: string): CodeGraphNode[] {
  return [
    node(repoId, "main-file", "file", "src/main.ts", "src/main.ts"),
    node(repoId, "util-file", "file", "src/util.ts", "src/util.ts"),
    node(repoId, "run", "function", "run", "src/main.ts"),
    node(repoId, "helper", "function", "helper", "src/util.ts"),
  ];
}

function graphEdges(repoId: string): CodeGraphEdge[] {
  return [
    {
      id: "main-contains-run",
      repo_id: repoId,
      source_id: "main-file",
      target_id: "run",
      type: "contains",
      confidence: 1,
      weight: 1,
      is_inferred: false,
      metadata: {},
    },
    {
      id: "util-contains-helper",
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
      "import { helper } from './util';\nexport function run() {\n  return helper(41);\n}",
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
): CodeGraphNode {
  return {
    id,
    repo_id: repoId,
    type,
    name,
    file_path: filePath,
    start_line: 1,
    end_line: 3,
    language: "typescript",
    symbol_id: `${filePath}:${name}:1`,
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
