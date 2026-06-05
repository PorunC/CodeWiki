import type { CodeWikiStoreApi } from "../db/types.js";
import {
  LlmCallError,
  type CachedLlmCompletion,
  type LlmOperation,
} from "../llm/cache.js";
import type {
  CodeGraphEdge,
  CodeGraphNode,
  GraphCommunity,
  GraphCommunityEdge,
  JsonObject,
} from "../types.js";
import { digest } from "../analysis/graphUtils.js";
import {
  nameGraphCommunities,
  type CommunityNamingResult,
} from "./communityNaming.js";
import {
  dedupeName,
  isGenericName,
  nonGenericFallbackName,
  normalizeCommunityName,
} from "./communityNamingRules.js";

type CommunityNamingLlm = {
  isConfigured(taskType: string): boolean;
  complete(
    repoId: string,
    operation: LlmOperation,
  ): Promise<CachedLlmCompletion>;
};

type CommunityNamingOptions = {
  maxCommunities?: number | undefined;
};

type CommunityNamingPayload = CommunityNamingResult & {
  communities: Array<{
    id: string;
    name: string;
    summary: string;
    node_count: number;
  }>;
  llm?: JsonObject | undefined;
};

type CommunityContext = {
  id: string;
  currentName: string;
  currentSummary: string;
  files: string[];
  symbols: Array<{
    name: string;
    type: string;
    file_path: string;
  }>;
  edgeTypes: string[];
};

type ProviderCommunityName = {
  id: string;
  name: string;
  summary: string;
};

export class CommunityNamingService {
  constructor(
    private readonly store: CodeWikiStoreApi,
    private readonly llm?: CommunityNamingLlm,
  ) {}

  async nameCommunities(
    repoId: string,
    options: CommunityNamingOptions = {},
  ): Promise<CommunityNamingPayload> {
    const baselineOptions =
      options.maxCommunities === undefined
        ? {}
        : { maxCommunities: options.maxCommunities };
    const baseline = await nameGraphCommunities(
      this.store,
      repoId,
      baselineOptions,
    );
    if (
      !this.llm?.isConfigured("community_summary") ||
      baseline.status === "no_communities" ||
      baseline.named_community_ids.length === 0
    ) {
      return {
        ...baseline,
        communities: await namedCommunityPayloads(
          this.store,
          repoId,
          baseline.named_community_ids,
        ),
      };
    }

    const contexts = await communityContexts(
      this.store,
      repoId,
      baseline.named_community_ids,
    );
    if (!contexts.length) {
      return {
        ...baseline,
        communities: await namedCommunityPayloads(
          this.store,
          repoId,
          baseline.named_community_ids,
        ),
        llm: { status: "fallback", error: "No community contexts available." },
      };
    }

    try {
      const completion = await this.llm.complete(repoId, {
        taskType: "community_summary",
        cacheKey: `graph-communities:${baseline.max_communities}`,
        modelAlias: "community_summary",
        promptVersion: "ts-community-summary-v1",
        inputPayload: {
          repo_id: repoId,
          max_communities: baseline.max_communities,
          communities: contexts,
        },
        messages: communityNamingMessages(repoId, contexts),
        completion: { responseFormat: "json_object" },
      });
      const parsed = normalizeProviderNames(
        completion.result.content,
        baseline.named_community_ids,
      );
      if (!parsed.names.length) {
        return {
          ...baseline,
          communities: await namedCommunityPayloads(
            this.store,
            repoId,
            baseline.named_community_ids,
          ),
          llm: {
            status: "fallback",
            error: parsed.errors.join("; ") || "No provider community names.",
            run_id: completion.run.id,
          },
        };
      }
      const providerResult = await applyProviderNames(
        this.store,
        repoId,
        baseline,
        parsed.names,
      );
      return {
        ...providerResult,
        communities: await namedCommunityPayloads(
          this.store,
          repoId,
          providerResult.named_community_ids,
        ),
        llm: llmMetadata("success", completion),
        errors: parsed.errors,
      };
    } catch (error) {
      return {
        ...baseline,
        communities: await namedCommunityPayloads(
          this.store,
          repoId,
          baseline.named_community_ids,
        ),
        llm: {
          status: "fallback",
          error: error instanceof Error ? error.message : String(error),
          run_id: error instanceof LlmCallError ? error.runId : null,
        },
      };
    }
  }
}

async function communityContexts(
  store: CodeWikiStoreApi,
  repoId: string,
  communityIds: string[],
): Promise<CommunityContext[]> {
  const graph = await store.getGraph(repoId);
  const communities = (await store.listGraphCommunities(repoId)).filter(
    (community) => communityIds.includes(community.id),
  );
  return communities.map((community) =>
    communityContext(community, graph.nodes, graph.edges),
  );
}

function communityContext(
  community: GraphCommunity,
  nodes: CodeGraphNode[],
  edges: CodeGraphEdge[],
): CommunityContext {
  const directNodeIds = new Set(community.node_ids);
  const directNodes = community.node_ids
    .map((nodeId) => nodes.find((node) => node.id === nodeId))
    .filter((node): node is CodeGraphNode => Boolean(node));
  const files = uniqueSorted(
    directNodes
      .map((node) => node.file_path)
      .filter((filePath) => filePath.length > 0),
  );
  const fileSet = new Set(files);
  const symbols = nodes
    .filter(
      (node) =>
        node.type !== "file" &&
        node.type !== "config" &&
        (directNodeIds.has(node.id) || fileSet.has(node.file_path)),
    )
    .sort(
      (left, right) =>
        left.file_path.localeCompare(right.file_path) ||
        (left.start_line ?? 0) - (right.start_line ?? 0) ||
        left.name.localeCompare(right.name),
    )
    .slice(0, 12)
    .map((node) => ({
      name: node.name,
      type: node.type,
      file_path: node.file_path,
    }));
  const edgeTypes = uniqueSorted(
    edges
      .filter(
        (edge) =>
          directNodeIds.has(edge.source_id) ||
          directNodeIds.has(edge.target_id),
      )
      .map((edge) => edge.type),
  );
  return {
    id: community.id,
    currentName: community.name,
    currentSummary: community.summary ?? "",
    files,
    symbols,
    edgeTypes,
  };
}

function communityNamingMessages(
  repoId: string,
  contexts: CommunityContext[],
): LlmOperation["messages"] {
  return [
    {
      role: "system",
      content: [
        "You name and summarize code graph communities.",
        'Return only JSON with shape {"communities":[{"id":string,"name":string,"summary":string}]}',
        "Use concise product-facing names, avoid generic words like community or cluster, and keep summaries source-grounded.",
      ].join(" "),
    },
    {
      role: "user",
      content: `Repository ${repoId} community contexts:\n${JSON.stringify({
        communities: contexts,
      })}`,
    },
  ];
}

function normalizeProviderNames(
  content: string,
  allowedIds: string[],
): { names: ProviderCommunityName[]; errors: string[] } {
  const errors: string[] = [];
  const payload = parseJsonObject(content, errors);
  if (!payload) {
    return { names: [], errors };
  }
  const communities = payload.communities;
  if (!Array.isArray(communities)) {
    return {
      names: [],
      errors: [
        ...errors,
        "Provider response must include a communities array.",
      ],
    };
  }
  const allowed = new Set(allowedIds);
  const seen = new Set<string>();
  const names: ProviderCommunityName[] = [];
  for (const item of communities) {
    if (!isRecord(item)) {
      errors.push("Provider community item was not an object.");
      continue;
    }
    const id = nonEmptyString(item.id);
    const name = nonEmptyString(item.name);
    const summary = nonEmptyString(item.summary);
    if (!id || !allowed.has(id)) {
      errors.push(`Provider returned an unknown community id: ${id ?? ""}`);
      continue;
    }
    if (seen.has(id)) {
      errors.push(`Provider returned a duplicate community id: ${id}`);
      continue;
    }
    if (!name || !summary) {
      errors.push(`Provider community ${id} needs a name and summary.`);
      continue;
    }
    seen.add(id);
    names.push({
      id,
      name: name.slice(0, 80),
      summary: summary.slice(0, 700),
    });
  }
  return { names, errors };
}

async function applyProviderNames(
  store: CodeWikiStoreApi,
  repoId: string,
  baseline: CommunityNamingResult,
  providerNames: ProviderCommunityName[],
): Promise<CommunityNamingResult> {
  const before = await store.listGraphCommunities(repoId);
  const providerById = new Map(providerNames.map((item) => [item.id, item]));
  const targetIds = new Set(baseline.named_community_ids);
  const seenNames = new Set(
    before
      .filter((community) => !targetIds.has(community.id))
      .map((community) => community.name.toLowerCase()),
  );
  const after = before.map((community, index) => {
    const provider = providerById.get(community.id);
    if (!provider) {
      return community;
    }
    const providerName = normalizeCommunityName(provider.name, community.name);
    const fallbackName = nonGenericFallbackName(community.name, index);
    const preferredName = isGenericName(providerName)
      ? fallbackName
      : providerName;
    const name = dedupeName(preferredName, seenNames);
    seenNames.add(name.toLowerCase());
    return {
      ...community,
      name,
      summary: provider.summary,
      summary_hash: digest(provider.summary),
    };
  });
  const edges = await store.listGraphCommunityEdges(repoId);
  await store.replaceGraphCommunities(repoId, after);
  await preserveCommunityEdges(store, repoId, after, edges);
  const renamedCount = renamedCountBetween(before, after);
  return {
    ...baseline,
    status: renamedCount > 0 ? "renamed" : "unchanged",
    renamed_count: renamedCount,
  };
}

async function namedCommunityPayloads(
  store: CodeWikiStoreApi,
  repoId: string,
  communityIds: string[],
): Promise<CommunityNamingPayload["communities"]> {
  return (await store.listGraphCommunities(repoId))
    .filter((community) => communityIds.includes(community.id))
    .sort((left, right) => {
      const leftIndex = communityIds.indexOf(left.id);
      const rightIndex = communityIds.indexOf(right.id);
      return leftIndex - rightIndex;
    })
    .map((community) => ({
      id: community.id,
      name: community.name,
      summary: community.summary ?? "",
      node_count: community.node_ids.length,
    }));
}

async function preserveCommunityEdges(
  store: CodeWikiStoreApi,
  repoId: string,
  communities: GraphCommunity[],
  edges: GraphCommunityEdge[],
): Promise<void> {
  if (!edges.length) {
    return;
  }
  const communityIds = new Set(communities.map((community) => community.id));
  await store.replaceGraphCommunityEdges(
    repoId,
    edges.filter(
      (edge) =>
        communityIds.has(edge.source_community_id) &&
        communityIds.has(edge.target_community_id),
    ),
  );
}

function renamedCountBetween(
  before: GraphCommunity[],
  after: GraphCommunity[],
): number {
  const beforeById = new Map(
    before.map((community) => [community.id, community]),
  );
  return after.filter((community) => {
    const previous = beforeById.get(community.id);
    return (
      previous !== undefined &&
      (previous.name !== community.name ||
        previous.summary !== community.summary)
    );
  }).length;
}

function parseJsonObject(content: string, errors: string[]): JsonObject | null {
  const trimmed = stripMarkdownFence(content.trim());
  const candidates = [trimmed, extractObject(trimmed)].filter(
    (candidate): candidate is string => Boolean(candidate),
  );
  for (const candidate of candidates) {
    try {
      const parsed = JSON.parse(candidate) as unknown;
      if (isRecord(parsed)) {
        return parsed as JsonObject;
      }
    } catch {
      // Try the next candidate below.
    }
  }
  errors.push("Provider community response was not valid JSON.");
  return null;
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

function nonEmptyString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function uniqueSorted(values: string[]): string[] {
  return [...new Set(values)].sort((left, right) => left.localeCompare(right));
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function llmMetadata(
  status: "success",
  completion: CachedLlmCompletion,
): JsonObject {
  return {
    status,
    cache_hit: completion.cacheHit,
    run_id: completion.run.id,
    model: completion.result.model,
    provider: completion.result.provider,
  };
}
