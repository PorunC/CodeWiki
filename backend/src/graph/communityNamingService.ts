import { digest } from "../analysis/graphUtils.js";
import { buildCommunityEdges } from "../analysis/graphCommunities.js";
import type { CodeWikiStoreApi } from "../db/types.js";
import { notFoundError } from "../errors.js";
import { type CachedLlmCompletion, type LlmOperation } from "../llm/cache.js";
import { dynamicJsonMessage, stableJsonMessage } from "../llm/messages.js";
import { loadPrompt } from "../services/prompts.js";
import type {
  CodeGraphEdge,
  CodeGraphNode,
  GraphCommunity,
  JsonObject,
  JsonValue,
  RepoDescriptor,
} from "../types.js";
import {
  dedupeName,
  fileLabel,
  humanizeName,
  isGenericName,
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

export type CommunityNamingPayload = {
  repo_id: string;
  status:
    | "renamed"
    | "unchanged"
    | "no_communities"
    | "partial"
    | "skipped"
    | "failed";
  renamed_count: number;
  community_count: number;
  max_communities: number;
  named_community_ids: string[];
  llm_run_id?: string | null | undefined;
  llm_run_ids?: string[] | undefined;
  errors: string[];
  communities: Array<{
    id: string;
    name: string;
    summary: string;
    node_count: number;
  }>;
  llm?: JsonObject | undefined;
};

const MAX_COMMUNITIES_PER_LLM_CALL = 40;
const COMMUNITIES_PER_BATCH = 8;
const MAX_COMMUNITY_FILES = 12;
const MAX_COMMUNITY_SYMBOLS = 16;
const MAX_COMMUNITY_EDGES = 10;
const MAX_NAME_LENGTH = 64;
const LLM_NOT_CONFIGURED_ERROR =
  "LLM community naming skipped because no LLM endpoint or API key is configured.";
const COMMUNITY_NAMING_SYSTEM_PROMPT = loadPrompt("community_summary.md");

export class CommunityNamingService {
  constructor(
    private readonly store: CodeWikiStoreApi,
    private readonly llm?: CommunityNamingLlm,
  ) {}

  async nameCommunities(
    repoId: string,
    options: CommunityNamingOptions = {},
  ): Promise<CommunityNamingPayload> {
    const repo = await this.store.getRepo(repoId);
    if (!repo) {
      throw notFoundError("Repository", repoId);
    }
    const maxCommunities = normalizeMaxCommunities(options.maxCommunities);
    const communities = await this.store.listGraphCommunities(repoId);
    if (!communities.length) {
      return {
        repo_id: repoId,
        status: "no_communities",
        renamed_count: 0,
        community_count: 0,
        max_communities: maxCommunities,
        named_community_ids: [],
        errors: [],
        communities: [],
      };
    }
    if (!this.llm) {
      throw new Error("LLM community naming service is not configured.");
    }

    const graph = await this.store.getGraph(repoId);
    const nodeById = new Map(graph.nodes.map((node) => [node.id, node]));
    const targets = selectNamingTargets(communities, maxCommunities);
    if (!targets.length) {
      return {
        repo_id: repoId,
        status: "unchanged",
        renamed_count: 0,
        community_count: communities.length,
        max_communities: maxCommunities,
        named_community_ids: [],
        errors: [],
        communities: await namedCommunityPayloads(this.store, repoId, []),
      };
    }

    let renamed = communities;
    const errors: string[] = [];
    const llmRunIds: string[] = [];
    let firstCompletion: CachedLlmCompletion | null = null;
    for (const [batchIndex, batch] of batches(
      targets,
      COMMUNITIES_PER_BATCH,
    ).entries()) {
      const payload = namingPayload(
        repo,
        batch,
        nodeById,
        graph.edges,
        renamed,
      );
      const fallbackNames = fallbackNamesForPayload(payload);
      const completion = await this.llm.complete(repoId, {
        taskType: "community_summary",
        cacheKey: `community_naming:batch:${batchIndex + 1}`,
        modelAlias: "community_namer",
        promptVersion: "community_naming:v2",
        inputPayload: payload,
        messages: communityNamingMessages(payload),
        completion: { responseFormat: "json_object" },
      });
      firstCompletion ??= completion;
      const applied = applyProviderNames(
        renamed,
        batch,
        completion.result.content,
        fallbackNames,
      );
      renamed = applied.communities;
      errors.push(
        ...applied.errors.map((error) => `batch ${batchIndex + 1}: ${error}`),
      );
      let runId = completion.run.id;
      if (applied.errors.length) {
        const updated = await this.store.updateLlmRunStatus(completion.run.id, {
          status: "partial",
          error: applied.errors.join("; "),
        });
        runId = updated?.id ?? runId;
      }
      llmRunIds.push(runId);
    }

    await this.store.replaceGraphCommunities(repoId, renamed);
    await this.store.replaceGraphCommunityEdges(
      repoId,
      buildCommunityEdges(repoId, renamed, graph.edges),
    );
    const targetIds = targets.map((community) => community.id);
    const renamedCount = renamedCountBetween(communities, renamed);
    return {
      repo_id: repoId,
      status: errors.length ? "partial" : "renamed",
      renamed_count: renamedCount,
      community_count: renamed.length,
      max_communities: maxCommunities,
      named_community_ids: targetIds,
      llm_run_id: llmRunIds[0] ?? null,
      llm_run_ids: llmRunIds,
      errors,
      communities: communitySummaries(renamed, targetIds),
      llm: {
        status: errors.length ? "partial" : "success",
        cache_hit: firstCompletion?.cacheHit ?? false,
        run_id: llmRunIds[0] ?? null,
        run_ids: llmRunIds,
        model: firstCompletion?.result.model ?? null,
        provider: firstCompletion?.result.provider ?? null,
      },
    };
  }

  async nameCommunitiesForAnalysis(
    repoId: string,
    options: CommunityNamingOptions = {},
  ): Promise<CommunityNamingPayload> {
    const maxCommunities = normalizeMaxCommunities(options.maxCommunities);
    try {
      if (!this.llm?.isConfigured("community_summary")) {
        const communities = await this.store.listGraphCommunities(repoId);
        return {
          repo_id: repoId,
          status: "skipped",
          renamed_count: 0,
          community_count: communities.length,
          max_communities: maxCommunities,
          named_community_ids: [],
          errors: [LLM_NOT_CONFIGURED_ERROR],
          communities: [],
        };
      }
      return await this.nameCommunities(repoId, options);
    } catch (error) {
      const communities = await this.store.listGraphCommunities(repoId);
      return {
        repo_id: repoId,
        status: "failed",
        renamed_count: 0,
        community_count: communities.length,
        max_communities: maxCommunities,
        named_community_ids: [],
        errors: [error instanceof Error ? error.message : String(error)],
        communities: [],
      };
    }
  }
}

export function communityNamingPayloadJson(
  payload: CommunityNamingPayload,
): JsonObject {
  const result: JsonObject = {};
  for (const [key, value] of Object.entries(payload)) {
    if (value !== undefined && isJsonValue(value)) {
      result[key] = value;
    }
  }
  return result;
}

function normalizeMaxCommunities(value: number | undefined): number {
  if (typeof value !== "number" || !Number.isInteger(value)) {
    return MAX_COMMUNITIES_PER_LLM_CALL;
  }
  return Math.max(1, Math.min(value, MAX_COMMUNITIES_PER_LLM_CALL));
}

function selectNamingTargets(
  communities: GraphCommunity[],
  maxCommunities: number,
): GraphCommunity[] {
  const limit = normalizeMaxCommunities(maxCommunities);
  const byLevel = new Map<number, GraphCommunity[]>();
  for (const community of communities) {
    const level = Number.isInteger(community.level) ? community.level : 0;
    byLevel.set(level, [...(byLevel.get(level) ?? []), community]);
  }
  const selected: GraphCommunity[] = [];
  const seen = new Set<string>();
  const add = (items: GraphCommunity[]) => {
    for (const community of items) {
      if (selected.length >= limit) {
        return;
      }
      if (!seen.has(community.id)) {
        selected.push(community);
        seen.add(community.id);
      }
    }
  };

  add(
    [...(byLevel.get(0) ?? [])].sort(
      (left, right) =>
        left.rank - right.rank ||
        right.node_ids.length - left.node_ids.length ||
        left.name.localeCompare(right.name),
    ),
  );
  for (const level of [...byLevel.keys()].filter((item) => item > 0).sort()) {
    add(
      [...(byLevel.get(level) ?? [])].sort(
        (left, right) =>
          right.node_ids.length - left.node_ids.length ||
          fileCount(right) - fileCount(left) ||
          left.rank - right.rank ||
          left.name.localeCompare(right.name),
      ),
    );
  }
  add(communities);
  return selected;
}

function namingPayload(
  repo: RepoDescriptor,
  communities: GraphCommunity[],
  nodeById: Map<string, CodeGraphNode>,
  edges: CodeGraphEdge[],
  allCommunities: GraphCommunity[],
): JsonObject {
  const communityById = new Map(
    allCommunities.map((community) => [community.id, community]),
  );
  return {
    repo: {
      id: repo.id,
      name: repo.name,
      path: repo.path,
    },
    task: "Name and summarize graph communities using only the provided files, symbols, deterministic summaries, and graph relationships. Keep node membership unchanged.",
    communities: communities.map((community) =>
      communityPayload(community, nodeById, edges, communityById),
    ),
    naming_rules: [
      "Use concise developer-facing subsystem names, 2-6 words.",
      "Prefer capability/workflow names over generic layer names.",
      "Avoid names like Backend Subsystem, Frontend Subsystem, Community 1, Cluster 23, Misc, Core.",
      "Do not invent modules, products, files, or dependencies.",
      "Return one object per input community id.",
    ],
    summary_rules: [
      "Write a fresh source-grounded summary, not a copy of the deterministic summary.",
      "Describe responsibility, important files or symbols, and boundary dependencies.",
      "Keep each summary to one or two concise sentences.",
      "Call out unclear boundaries only when the graph evidence supports that uncertainty.",
    ],
    required_json_shape: {
      communities: [
        {
          id: "community-id",
          name: "GraphRAG Retrieval",
          summary:
            "One source-grounded sentence describing responsibility and boundaries.",
        },
      ],
    },
  };
}

function communityPayload(
  community: GraphCommunity,
  nodeById: Map<string, CodeGraphNode>,
  edges: CodeGraphEdge[],
  communityById: Map<string, GraphCommunity>,
): JsonObject {
  const nodeIds = new Set(community.node_ids);
  const files = uniqueSorted(
    community.node_ids.flatMap((nodeId) => {
      const filePath = nodeById.get(nodeId)?.file_path;
      return filePath ? [filePath] : [];
    }),
  );
  const symbols = community.node_ids.flatMap((nodeId) => {
    const node = nodeById.get(nodeId);
    return node && node.type !== "file"
      ? [
          {
            name: node.name,
            type: node.type,
            file_path: node.file_path,
          },
        ]
      : [];
  });
  const internalEdges = edges
    .filter(
      (edge) => nodeIds.has(edge.source_id) && nodeIds.has(edge.target_id),
    )
    .slice(0, MAX_COMMUNITY_EDGES)
    .map((edge) => edgePayload(edge, nodeById));
  const boundaryEdges = edges
    .filter(
      (edge) => nodeIds.has(edge.source_id) !== nodeIds.has(edge.target_id),
    )
    .slice(0, MAX_COMMUNITY_EDGES)
    .map((edge) => edgePayload(edge, nodeById));
  const parent = community.parent_id
    ? communityById.get(community.parent_id)
    : null;
  return compactJsonObject({
    id: community.id,
    current_name: community.name,
    level: community.level,
    parent_id: community.parent_id,
    parent_name: parent?.name,
    ancestor_names: ancestorNames(community, communityById),
    rank: community.rank,
    node_count: community.node_ids.length,
    files: files.slice(0, MAX_COMMUNITY_FILES),
    symbols: symbols.slice(0, MAX_COMMUNITY_SYMBOLS),
    deterministic_summary: community.summary,
    internal_edges: internalEdges,
    boundary_edges: boundaryEdges,
  });
}

function edgePayload(
  edge: CodeGraphEdge,
  nodeById: Map<string, CodeGraphNode>,
): JsonObject {
  const source = nodeById.get(edge.source_id);
  const target = nodeById.get(edge.target_id);
  return {
    type: edge.type,
    source: source?.name ?? edge.source_id,
    source_type: source?.type ?? "",
    target: target?.name ?? edge.target_id,
    target_type: target?.type ?? "",
    confidence: edge.confidence,
  };
}

function communityNamingMessages(
  payload: JsonObject,
): LlmOperation["messages"] {
  return [
    {
      role: "system",
      content: COMMUNITY_NAMING_SYSTEM_PROMPT,
    },
    {
      role: "user",
      content: stableJsonMessage("Stable community naming contract", {
        instructions: "Return community names and summaries as JSON.",
      }),
    },
    {
      role: "user",
      content: dynamicJsonMessage("Community naming payload", payload),
    },
  ];
}

function applyProviderNames(
  allCommunities: GraphCommunity[],
  targetCommunities: GraphCommunity[],
  content: string,
  fallbackNames: Map<string, string>,
): { communities: GraphCommunity[]; errors: string[] } {
  const errors: string[] = [];
  const payload = parseJsonObject(content, errors);
  if (!payload) {
    return { communities: allCommunities, errors };
  }
  const rawItems = payload.communities;
  if (!Array.isArray(rawItems)) {
    return {
      communities: allCommunities,
      errors: ["LLM response must contain a communities array."],
    };
  }
  const byId = new Map(
    allCommunities.map((community) => [community.id, community]),
  );
  const targetIds = new Set(targetCommunities.map((community) => community.id));
  const updates = new Map<string, GraphCommunity>();
  const seenNames = new Set<string>();
  rawItems.forEach((rawItem, index) => {
    if (!isRecord(rawItem)) {
      errors.push(`communities[${index}] must be an object.`);
      return;
    }
    const communityId = stringValue(rawItem.id) ?? "";
    if (!targetIds.has(communityId)) {
      errors.push(`communities[${index}] uses unknown community id.`);
      return;
    }
    const community = byId.get(communityId);
    if (!community) {
      return;
    }
    let name = normalizeName(rawItem.name, community.name);
    if (isGenericName(name)) {
      name = nonGenericFallbackName(
        fallbackNames.get(communityId) ?? community.name,
        index,
      );
    }
    if (isGenericName(name)) {
      name = `Code Area ${index + 1}`;
    }
    name = dedupeName(name, seenNames);
    seenNames.add(name.toLowerCase());
    const summary = normalizeSummary(rawItem.summary, community.summary ?? "");
    updates.set(communityId, {
      ...community,
      name,
      summary,
      summary_hash: digest(summary),
    });
  });
  return {
    communities: allCommunities.map(
      (community) => updates.get(community.id) ?? community,
    ),
    errors,
  };
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
  errors.push("LLM did not return a JSON object.");
  return null;
}

function namedCommunityPayloads(
  store: CodeWikiStoreApi,
  repoId: string,
  communityIds: string[],
): Promise<CommunityNamingPayload["communities"]> {
  return Promise.resolve(store.listGraphCommunities(repoId)).then(
    (communities) => communitySummaries(communities, communityIds),
  );
}

function communitySummaries(
  communities: GraphCommunity[],
  communityIds: string[],
): CommunityNamingPayload["communities"] {
  const ordered =
    communityIds.length > 0
      ? communities
          .filter((community) => communityIds.includes(community.id))
          .sort(
            (left, right) =>
              communityIds.indexOf(left.id) - communityIds.indexOf(right.id),
          )
      : communities;
  return ordered.map((community) => ({
    id: community.id,
    name: community.name,
    summary: community.summary ?? "",
    node_count: community.node_ids.length,
  }));
}

function fallbackNamesForPayload(payload: JsonObject): Map<string, string> {
  const names = new Map<string, string>();
  const communities = payload.communities;
  if (!Array.isArray(communities)) {
    return names;
  }
  for (const item of communities) {
    if (isRecord(item)) {
      const id = stringValue(item.id);
      if (id) {
        names.set(id, fallbackNameFromPayload(item));
      }
    }
  }
  return names;
}

function fallbackNameFromPayload(item: Record<string, unknown>): string {
  const files = Array.isArray(item.files)
    ? item.files.filter(
        (filePath): filePath is string => typeof filePath === "string",
      )
    : [];
  const labels = files
    .map(fileLabel)
    .filter(
      (label) => label && !["index", "main"].includes(label.toLowerCase()),
    );
  const uniqueLabels = uniquePreserveOrder(labels);
  if (uniqueLabels.length === 1 && uniqueLabels[0]) {
    return uniqueLabels[0];
  }
  if (uniqueLabels.length > 1 && uniqueLabels[0] && uniqueLabels[1]) {
    return `${uniqueLabels[0]} and ${uniqueLabels[1]}`;
  }

  const symbols = Array.isArray(item.symbols) ? item.symbols : [];
  for (const symbol of symbols) {
    if (!isRecord(symbol)) {
      continue;
    }
    const name = stringValue(symbol.name);
    if (name && !name.startsWith("_")) {
      return humanizeName(name);
    }
  }
  return stringValue(item.current_name) ?? "Subsystem";
}

function normalizeName(value: unknown, fallback: string): string {
  const name = scalarString(value)
    .replace(/\s+/g, " ")
    .trim()
    .replace(/^(?:community|cluster)\s+\d+\s*[:-]\s*/i, "")
    .slice(0, MAX_NAME_LENGTH)
    .replace(/^[\s:-]+|[\s:-]+$/g, "");
  return name || fallback;
}

function normalizeSummary(value: unknown, fallback: string): string {
  const summary = scalarString(value).replace(/\s+/g, " ").trim();
  return (summary || fallback).slice(0, 800).trim();
}

function scalarString(value: unknown): string {
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return "";
}

function nonGenericFallbackName(name: string, index: number): string {
  const fallback = `Code Area ${index + 1}`;
  const candidate = normalizeName(name, fallback);
  return isGenericName(candidate) ? fallback : candidate;
}

function ancestorNames(
  community: GraphCommunity,
  communityById: Map<string, GraphCommunity>,
): string[] {
  const names: string[] = [];
  const seen = new Set<string>();
  let parentId = community.parent_id;
  while (parentId && !seen.has(parentId)) {
    seen.add(parentId);
    const parent = communityById.get(parentId);
    if (!parent) {
      break;
    }
    names.push(parent.name);
    parentId = parent.parent_id;
  }
  return names.reverse();
}

function fileCount(community: GraphCommunity): number {
  return new Set(
    community.node_ids.map((nodeId) => {
      const index = nodeId.lastIndexOf(":");
      return index >= 0 ? nodeId.slice(0, index) : nodeId;
    }),
  ).size;
}

function batches<T>(items: T[], size: number): T[][] {
  const result: T[][] = [];
  for (let index = 0; index < items.length; index += size) {
    result.push(items.slice(index, index + size));
  }
  return result;
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

function compactJsonObject(values: Record<string, unknown>): JsonObject {
  const payload: JsonObject = {};
  for (const [key, value] of Object.entries(values)) {
    if (value === undefined || value === null || value === "") {
      continue;
    }
    if (Array.isArray(value) && !value.length) {
      continue;
    }
    if (isJsonValue(value)) {
      payload[key] = value;
    }
  }
  return payload;
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

function stripMarkdownFence(value: string): string {
  const fence = /^```(?:json)?\s*([\s\S]*?)\s*```$/i.exec(value);
  return fence?.[1]?.trim() ?? value;
}

function extractObject(value: string): string | null {
  const start = value.indexOf("{");
  const end = value.lastIndexOf("}");
  return start >= 0 && end > start ? value.slice(start, end + 1) : null;
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function uniqueSorted(values: string[]): string[] {
  return [...new Set(values)].sort((left, right) => left.localeCompare(right));
}

function uniquePreserveOrder(values: string[]): string[] {
  const seen = new Set<string>();
  const unique: string[] = [];
  for (const value of values) {
    const key = value.toLowerCase();
    if (!seen.has(key)) {
      seen.add(key);
      unique.push(value);
    }
  }
  return unique;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
