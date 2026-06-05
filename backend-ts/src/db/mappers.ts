import type {
  AnalysisRun,
  CodeChunk,
  CodeChunkEmbedding,
  CodeGraphEdge,
  CodeGraphNode,
  DocCatalog,
  DocPage,
  GraphCommunity,
  GraphCommunityEdge,
  JsonObject,
  JsonValue,
  LlmRun,
  RepoDescriptor,
  RetrievalTrace,
} from "../types.js";

export type Row = Record<string, unknown>;

export function repoFromRow(row: Row): RepoDescriptor {
  return {
    id: stringValue(row.id),
    name: stringValue(row.name),
    path: stringValue(row.path),
    source_type: stringValue(row.source_type),
    git_url: nullableString(row.git_url),
    commit_hash: nullableString(row.commit_hash),
    created_at: nullableString(row.created_at),
    updated_at: nullableString(row.updated_at),
  };
}

export function analysisRunFromRow(row: Row): AnalysisRun {
  return {
    id: stringValue(row.id),
    repo_id: stringValue(row.repo_id),
    status: stringValue(row.status),
    started_at: nullableString(row.started_at),
    finished_at: nullableString(row.finished_at),
    error: nullableString(row.error),
    stats: parseJsonObject(row.stats_json),
  };
}

export function nodeFromRow(row: Row): CodeGraphNode {
  return {
    id: stringValue(row.id),
    repo_id: stringValue(row.repo_id),
    type: stringValue(row.type),
    name: stringValue(row.name),
    file_path: stringValue(row.file_path),
    start_line: nullableNumber(row.start_line),
    end_line: nullableNumber(row.end_line),
    language: nullableString(row.language),
    symbol_id: nullableString(row.symbol_id),
    summary: nullableString(row.summary),
    hash: stringValue(row.hash),
    metadata: parseJsonObject(row.metadata_json),
  };
}

export function edgeFromRow(row: Row): CodeGraphEdge {
  return {
    id: stringValue(row.id),
    repo_id: stringValue(row.repo_id),
    source_id: stringValue(row.source_id),
    target_id: stringValue(row.target_id),
    type: stringValue(row.type),
    confidence: numberValue(row.confidence, 1),
    weight: numberValue(row.weight, 1),
    is_inferred: Boolean(row.is_inferred),
    metadata: parseJsonObject(row.metadata_json),
  };
}

export function communityFromRow(row: Row): GraphCommunity {
  return {
    id: stringValue(row.id),
    repo_id: stringValue(row.repo_id),
    name: stringValue(row.name),
    level: numberValue(row.level, 0),
    parent_id: nullableString(row.parent_id),
    rank: numberValue(row.rank, 0),
    node_ids: parseStringArray(row.node_ids_json),
    summary: nullableString(row.summary),
    summary_hash: nullableString(row.summary_hash),
    created_at: nullableString(row.created_at),
  };
}

export function communityEdgeFromRow(row: Row): GraphCommunityEdge {
  return {
    id: stringValue(row.id),
    repo_id: stringValue(row.repo_id),
    source_community_id: stringValue(row.source_community_id),
    target_community_id: stringValue(row.target_community_id),
    type: stringValue(row.type),
    weight: numberValue(row.weight, 1),
    confidence: numberValue(row.confidence, 1),
    reason: nullableString(row.reason),
    evidence_edge_ids: parseStringArray(row.evidence_edge_ids_json),
    created_at: nullableString(row.created_at),
  };
}

export function chunkFromRow(row: Row): CodeChunk {
  return {
    id: stringValue(row.id),
    repo_id: stringValue(row.repo_id),
    node_id: nullableString(row.node_id),
    file_path: stringValue(row.file_path),
    start_line: numberValue(row.start_line, 0),
    end_line: numberValue(row.end_line, 0),
    content: stringValue(row.content),
    content_hash: stringValue(row.content_hash),
    token_count: numberValue(row.token_count, 0),
  };
}

export function embeddingFromRow(row: Row): CodeChunkEmbedding {
  return {
    id: stringValue(row.id),
    repo_id: stringValue(row.repo_id),
    chunk_id: stringValue(row.chunk_id),
    model: stringValue(row.model),
    dimensions: numberValue(row.dimensions, 0),
    embedding: parseNumberArray(row.embedding_json),
    content_hash: stringValue(row.content_hash),
    created_at: nullableString(row.created_at),
  };
}

export function catalogFromRow(row: Row): DocCatalog {
  return {
    id: stringValue(row.id),
    repo_id: stringValue(row.repo_id),
    language_code: stringValue(row.language_code),
    title: stringValue(row.title),
    structure: parseJsonObject(row.structure_json),
    generated_at: nullableString(row.generated_at),
  };
}

export function pageFromRow(row: Row): DocPage {
  return {
    id: stringValue(row.id),
    repo_id: stringValue(row.repo_id),
    language_code: stringValue(row.language_code),
    slug: stringValue(row.slug),
    title: stringValue(row.title),
    parent_slug: nullableString(row.parent_slug),
    markdown: stringValue(row.markdown),
    source_refs: parseJsonArray(row.source_refs_json).filter(isJsonObject),
    graph_refs: parseStringArray(row.graph_refs_json),
    status: stringValue(row.status),
    updated_at: nullableString(row.updated_at),
  };
}

export function retrievalTraceFromRow(row: Row): RetrievalTrace {
  const payload = parseJsonObject(row.payload_json);
  return {
    repo_id: stringValue(payload.repo_id) || stringValue(row.repo_id),
    query: stringValue(payload.query) || stringValue(row.query),
    max_hops: numberValue(payload.max_hops, numberValue(row.max_hops, 2)),
    trace_id: stringValue(payload.trace_id) || stringValue(row.id),
    seed_nodes: jsonObjectArray(payload.seed_nodes),
    expanded_nodes: jsonObjectArray(payload.expanded_nodes),
    source_chunks: jsonObjectArray(payload.source_chunks),
    related_edges: jsonObjectArray(payload.related_edges),
    community_summaries: jsonObjectArray(payload.community_summaries),
    community_edges: jsonObjectArray(payload.community_edges),
    context_pack: isJsonObjectValue(payload.context_pack)
      ? payload.context_pack
      : {},
    chunks: codeChunkArray(payload.chunks),
    nodes: jsonObjectArray(payload.nodes),
    edges: jsonObjectArray(payload.edges),
    communities: jsonObjectArray(payload.communities),
    context: stringValue(payload.context),
    created_at:
      nullableString(payload.created_at) ?? nullableString(row.created_at),
  };
}

export function llmRunFromRow(row: Row): LlmRun {
  return {
    id: stringValue(row.id),
    repo_id: stringValue(row.repo_id),
    task_type: stringValue(row.task_type),
    provider: nullableString(row.provider),
    model: stringValue(row.model),
    model_alias: nullableString(row.model_alias),
    prompt_version: nullableString(row.prompt_version),
    input_hash: stringValue(row.input_hash),
    cache_key: stringValue(row.cache_key),
    tokens_in: numberValue(row.tokens_in, 0),
    tokens_out: numberValue(row.tokens_out, 0),
    cost_usd: nullableNumber(row.cost_usd),
    duration_ms: nullableNumber(row.duration_ms),
    response_content: stringValue(row.response_content),
    response_usage: parseJsonObject(row.response_usage_json),
    cached: Boolean(row.cached),
    status: stringValue(row.status),
    error: nullableString(row.error),
    created_at: nullableString(row.created_at),
  };
}

export function scoreNode(node: CodeGraphNode, query: string): number {
  if (!query) {
    return 0.1;
  }
  let score = 0;
  if (node.name.toLowerCase() === query) {
    score += 5;
  }
  if (node.name.toLowerCase().includes(query)) {
    score += 3;
  }
  if (node.file_path.toLowerCase().includes(query)) {
    score += 1.5;
  }
  if ((node.summary ?? "").toLowerCase().includes(query)) {
    score += 1;
  }
  return score;
}

export function stringifyJson(value: JsonValue): string {
  return JSON.stringify(value);
}

export function normalizeLanguage(
  languageCode: string | undefined | null,
): string {
  const language = languageCode?.trim().toLowerCase();
  return language || "en";
}

export function isoNow(): string {
  return new Date().toISOString();
}

function parseJsonObject(value: unknown): JsonObject {
  const parsed = parseJson(value, {});
  return isJsonObject(parsed) ? parsed : {};
}

function parseJsonArray(value: unknown): JsonValue[] {
  const parsed = parseJson(value, []);
  return Array.isArray(parsed) ? parsed : [];
}

function parseStringArray(value: unknown): string[] {
  return parseJsonArray(value).filter(
    (item): item is string => typeof item === "string",
  );
}

function parseNumberArray(value: unknown): number[] {
  return parseJsonArray(value).filter(
    (item): item is number => typeof item === "number" && Number.isFinite(item),
  );
}

function jsonObjectArray(value: unknown): JsonObject[] {
  return Array.isArray(value) ? value.filter(isJsonObjectValue) : [];
}

function codeChunkArray(value: unknown): CodeChunk[] {
  return Array.isArray(value) ? value.filter(isCodeChunk) : [];
}

function parseJson(value: unknown, fallback: JsonValue): JsonValue {
  if (typeof value !== "string") {
    return fallback;
  }
  try {
    return JSON.parse(value) as JsonValue;
  } catch {
    return fallback;
  }
}

function isJsonObject(value: JsonValue): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isJsonObjectValue(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isCodeChunk(value: unknown): value is CodeChunk {
  if (!isJsonObjectValue(value)) {
    return false;
  }
  return (
    typeof value.id === "string" &&
    typeof value.repo_id === "string" &&
    (typeof value.node_id === "string" || value.node_id === null) &&
    typeof value.file_path === "string" &&
    typeof value.start_line === "number" &&
    typeof value.end_line === "number" &&
    typeof value.content === "string" &&
    typeof value.content_hash === "string" &&
    typeof value.token_count === "number"
  );
}

function stringValue(value: unknown): string {
  if (typeof value === "string") {
    return value;
  }
  if (
    typeof value === "number" ||
    typeof value === "boolean" ||
    typeof value === "bigint"
  ) {
    return String(value);
  }
  return "";
}

function nullableString(value: unknown): string | null {
  if (value === null || value === undefined || value === "") {
    return null;
  }
  if (typeof value === "string") {
    return value;
  }
  if (
    typeof value === "number" ||
    typeof value === "boolean" ||
    typeof value === "bigint"
  ) {
    return String(value);
  }
  return null;
}

function numberValue(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function nullableNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}
