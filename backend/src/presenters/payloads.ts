import type { CodeWikiSettings } from "../config.js";
import {
  defaultLlmProfile,
  llmTaskProfiles,
  type ResolvedLlmProfile,
} from "../llm/modelRouter.js";
import { filePayload, fileTreePayload } from "../scanner/scanner.js";
import type {
  AnalysisResult,
  JsonObject,
  JsonValue,
  RepoDescriptor,
  RepoFile,
  RepoFileScanResult,
  RepoScanResult,
  RepositoryUpdateResult,
} from "../types.js";

export type RepoPayload = {
  id: string;
  name: string;
  path: string;
  source_type: string;
  git_url: string;
  commit_hash: string;
};

export type LlmProfilePayload = {
  model: string;
  provider_type: string;
  endpoint: string;
  has_api_key: boolean;
  stream: boolean;
  max_tokens: number | null;
};

export type ConfigPayload = {
  app_name: string;
  database_url: string;
  database_path: string;
  storage_dir: string;
  host: string;
  port: number;
  log: {
    level: string;
    format: string;
  };
  llm: {
    mode: string;
    default: LlmProfilePayload;
    profiles: Record<string, LlmProfilePayload>;
  };
};

export function repoPayload(repo: RepoDescriptor): RepoPayload {
  return {
    id: repo.id,
    name: repo.name,
    path: repo.path,
    source_type: repo.source_type,
    git_url: repo.git_url ?? "",
    commit_hash: repo.commit_hash ?? "",
  };
}

export function repoScanPayload(scan: RepoScanResult): JsonObject {
  return {
    repo: repoPayload(scan.repo),
    files: scan.files.map((file) => ({
      ...filePayload(file),
      sha256: file.sha256,
      last_commit_at: file.last_commit_at ?? null,
    })),
    scanned_count: scan.scanned_count,
    ignored_count: scan.ignored_count,
    skipped_count: scan.skipped_count,
  };
}

export function repoFilesPayload(
  repo: RepoDescriptor,
  scan: RepoFileScanResult,
  options: { sourceOnly?: boolean } = {},
): {
  repo_id: string;
  root: Record<string, unknown>;
  files: Array<Record<string, unknown>>;
  scanned_count: number;
  ignored_count: number;
  skipped_count: number;
} {
  const files = options.sourceOnly
    ? scan.files.filter((file: RepoFile) => file.is_source)
    : scan.files;
  return {
    repo_id: repo.id,
    root: fileTreePayload(repo, files),
    files: files.map(filePayload),
    scanned_count: scan.scanned_count,
    ignored_count: scan.ignored_count,
    skipped_count: scan.skipped_count,
  };
}

export function analysisRunPayload(result: AnalysisResult): JsonObject {
  return {
    run_id: result.run_id,
    id: result.run_id,
    repo_id: result.repo_id,
    status: result.status,
    started_at: null,
    finished_at: new Date().toISOString(),
    error: null,
    stats: analysisStatsPayload(result),
    ...analysisStatsPayload(result),
  };
}

export function updatePayloadFromAnalysis(
  result: RepositoryUpdateResult,
  wikiRegeneration: unknown,
): JsonObject {
  return {
    run_id: result.run_id,
    repo_id: result.repo_id,
    status: result.status,
    ...analysisStatsPayload(result),
    plan: result.plan,
    stale_pages: result.stale_pages,
    wiki_regeneration: jsonValueOrObject(wikiRegeneration),
  };
}

export function llmProfilePayload(
  profile: CodeWikiSettings["llm"]["default"] | ResolvedLlmProfile,
): LlmProfilePayload {
  return {
    model: profile.model ?? "",
    provider_type: profile.provider_type ?? "",
    endpoint: profile.endpoint ?? "",
    has_api_key: Boolean(profile.api_key),
    stream:
      "stream" in profile && typeof profile.stream === "boolean"
        ? profile.stream
        : false,
    max_tokens: profile.max_tokens,
  };
}

export function llmModelsPayload(settings: CodeWikiSettings): JsonObject {
  return {
    mode: settings.llm.mode,
    default_profile: llmProfilePayload(defaultLlmProfile(settings)),
    profiles: Object.fromEntries(
      Object.entries(llmTaskProfiles(settings)).map(([name, profile]) => [
        name,
        llmProfilePayload(profile),
      ]),
    ),
  };
}

export function configPayload(settings: CodeWikiSettings): ConfigPayload {
  return {
    app_name: settings.appName,
    database_url: settings.databaseUrl,
    database_path: settings.databasePath,
    storage_dir: settings.storageDir,
    host: settings.host,
    port: settings.port,
    log: {
      level: settings.log.level,
      format: settings.log.format,
    },
    llm: {
      mode: settings.llm.mode,
      default: llmProfilePayload(settings.llm.default),
      profiles: Object.fromEntries(
        Object.entries(settings.llm.profiles).map(([name, profile]) => [
          name,
          llmProfilePayload(profile),
        ]),
      ),
    },
  };
}

function analysisStatsPayload(result: AnalysisResult): JsonObject {
  return {
    mode: result.mode,
    scanned_count: result.scanned_count,
    parsed_file_count: result.parsed_file_count,
    reused_file_count: result.reused_file_count,
    node_count: result.node_count,
    edge_count: result.edge_count,
    chunk_count: result.chunk_count,
    community_count: result.community_count,
    community_count_by_level: result.community_count_by_level,
    errors: result.errors,
  };
}

function jsonValueOrObject(value: unknown): JsonValue {
  return isJsonValue(value) ? value : {};
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
  if (typeof value === "object") {
    return Object.values(value).every(isJsonValue);
  }
  return false;
}
