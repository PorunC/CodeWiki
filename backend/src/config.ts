import { mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { environmentWithDotEnv } from "./services/envConfig.js";

export type LlmProfileSettings = {
  model: string | null;
  provider_type: string | null;
  endpoint: string | null;
  api_key: string | null;
  max_tokens: number | null;
};

export type CodeWikiSettings = {
  appName: string;
  databaseUrl: string;
  databasePath: string;
  storageDir: string;
  host: string;
  port: number;
  staticDir: string | null;
  llm: {
    mode: string;
    default: LlmProfileSettings;
    profiles: Record<string, LlmProfileSettings>;
  };
};

export function getSettings(env?: NodeJS.ProcessEnv): CodeWikiSettings {
  const sourceEnv = env ?? environmentWithDotEnv();
  const databaseUrl =
    sourceEnv.CODEWIKI_DATABASE_URL ?? "sqlite:///./data/codewiki.sqlite3";
  const databasePath = sqlitePathFromUrl(databaseUrl);
  mkdirSync(dirname(databasePath), { recursive: true });

  return {
    appName: sourceEnv.CODEWIKI_APP_NAME ?? "Code Wiki Platform",
    databaseUrl,
    databasePath,
    storageDir: resolve(sourceEnv.CODEWIKI_STORAGE_DIR ?? "./storage"),
    host: sourceEnv.CODEWIKI_HOST ?? sourceEnv.BACKEND_HOST ?? "127.0.0.1",
    port: parsePort(sourceEnv.CODEWIKI_PORT ?? sourceEnv.BACKEND_PORT, 8000),
    staticDir: sourceEnv.CODEWIKI_STATIC_DIR
      ? resolve(sourceEnv.CODEWIKI_STATIC_DIR)
      : null,
    llm: {
      mode: sourceEnv.CODEWIKI_LLM__MODE ?? "sdk",
      default: readProfile(sourceEnv, "CODEWIKI_LLM__DEFAULT__"),
      profiles: readProfiles(sourceEnv),
    },
  };
}

export function sqlitePathFromUrl(databaseUrl: string): string {
  const normalized = databaseUrl.replace(/^sqlite\+aiosqlite:/, "sqlite:");
  if (normalized === "sqlite:///:memory:" || normalized === "sqlite::memory:") {
    return ":memory:";
  }
  const match = normalized.match(/^sqlite:\/\/\/(.+)$/);
  if (!match) {
    throw new Error(
      `Unsupported database URL for the TypeScript backend: ${databaseUrl}. ` +
        "Use sqlite:///path or sqlite+aiosqlite:///path.",
    );
  }
  const rawPath = match[1] ?? "";
  if (rawPath.startsWith("/")) {
    return rawPath;
  }
  return resolve(rawPath);
}

function parsePort(value: string | undefined, fallback: number): number {
  if (!value) {
    return fallback;
  }
  const parsed = Number.parseInt(value, 10);
  if (!Number.isInteger(parsed) || parsed < 1 || parsed > 65535) {
    throw new Error(`Port must be between 1 and 65535, got ${value}`);
  }
  return parsed;
}

function readProfile(
  env: NodeJS.ProcessEnv,
  prefix: string,
): LlmProfileSettings {
  return {
    model: env[`${prefix}MODEL`] ?? null,
    provider_type: env[`${prefix}PROVIDER_TYPE`] ?? null,
    endpoint: env[`${prefix}ENDPOINT`] ?? null,
    api_key: env[`${prefix}API_KEY`] ?? null,
    max_tokens: parseNullableInt(env[`${prefix}MAX_TOKENS`]),
  };
}

function readProfiles(
  env: NodeJS.ProcessEnv,
): Record<string, LlmProfileSettings> {
  const profiles: Record<string, LlmProfileSettings> = {};
  const prefix = "CODEWIKI_LLM__PROFILES__";
  for (const key of Object.keys(env)) {
    if (!key.startsWith(prefix)) {
      continue;
    }
    const [, rest] = key.split(prefix);
    const [profile] = (rest ?? "").split("__");
    if (!profile) {
      continue;
    }
    const normalized = profile.toLowerCase();
    profiles[normalized] = readProfile(env, `${prefix}${profile}__`);
  }
  return profiles;
}

function parseNullableInt(value: string | undefined): number | null {
  if (value === undefined || value.trim() === "") {
    return null;
  }
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) ? parsed : null;
}
