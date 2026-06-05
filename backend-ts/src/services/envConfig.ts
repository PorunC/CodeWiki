import {
  copyFileSync,
  existsSync,
  mkdirSync,
  readFileSync,
  writeFileSync,
} from "node:fs";
import { dirname, resolve } from "node:path";

const ENV_KEY_PATTERN = /^[A-Za-z_][A-Za-z0-9_]*$/;
const ENV_ASSIGNMENT_PATTERN =
  /^(\s*(?:export\s+)?)([A-Za-z_][A-Za-z0-9_]*)(\s*=\s*)(.*)$/;
const PLAIN_VALUE_PATTERN = /^[A-Za-z0-9_./:@+\-,]*$/;

export const LLM_PROFILES = [
  "default",
  "catalog",
  "community_summary",
  "cluster",
  "page",
  "translation",
  "qa",
  "embedding",
] as const;

const COMMON_CONFIG_KEYS = [
  "CODEWIKI_APP_NAME",
  "CODEWIKI_DATABASE_URL",
  "CODEWIKI_STORAGE_DIR",
  "CODEWIKI_HOST",
  "CODEWIKI_PORT",
  "CODEWIKI_STATIC_DIR",
  "CODEWIKI_LLM__MODE",
  "CODEWIKI_LLM__DEFAULT__MODEL",
  "CODEWIKI_LLM__DEFAULT__PROVIDER_TYPE",
  "CODEWIKI_LLM__DEFAULT__ENDPOINT",
  "CODEWIKI_LLM__DEFAULT__API_KEY",
  "CODEWIKI_LLM__DEFAULT__MAX_TOKENS",
  "CODEWIKI_LLM__TIMEOUT_SECONDS",
  "CODEWIKI_LLM__MAX_RETRIES",
  "CODEWIKI_LLM__CACHE_ENABLED",
  "CODEWIKI_WIKI_BASE_LANGUAGE",
  "CODEWIKI_WIKI_TRANSLATION_LANGUAGES",
] as const;

const SECRET_KEY_PARTS = ["API_KEY", "TOKEN", "SECRET", "PASSWORD"] as const;

export const DEFAULT_ENV_CONTENT = `# CodeWiki TypeScript backend
CODEWIKI_APP_NAME=Code Wiki Platform
CODEWIKI_DATABASE_URL=sqlite:///./data/codewiki.sqlite3
CODEWIKI_STORAGE_DIR=./storage

CODEWIKI_LLM__MODE=sdk
CODEWIKI_LLM__DEFAULT__MODEL=provider/strong-coding-model
CODEWIKI_LLM__DEFAULT__PROVIDER_TYPE=
CODEWIKI_LLM__DEFAULT__ENDPOINT=
CODEWIKI_LLM__DEFAULT__API_KEY=

CODEWIKI_WIKI_BASE_LANGUAGE=en
CODEWIKI_WIKI_TRANSLATION_LANGUAGES=
`;

export type LlmProfileName = (typeof LLM_PROFILES)[number];

export type EnvAssignment = {
  key: string;
  value: string;
};

export function defaultEnvFile(cwd = process.cwd()): string {
  return resolve(cwd, ".env");
}

export function environmentWithDotEnv(
  env: NodeJS.ProcessEnv = process.env,
  envFile = defaultEnvFile(),
): NodeJS.ProcessEnv {
  return {
    ...readEnvValues(envFile),
    ...env,
  };
}

export function ensureEnvFile(envFile: string, exampleFile?: string): boolean {
  if (existsSync(envFile)) {
    return false;
  }
  mkdirSync(dirname(envFile), { recursive: true });
  if (exampleFile && existsSync(exampleFile)) {
    copyFileSync(exampleFile, envFile);
  } else {
    writeFileSync(envFile, DEFAULT_ENV_CONTENT, "utf8");
  }
  return true;
}

export function readEnvValues(envFile: string): Record<string, string> {
  if (!existsSync(envFile)) {
    return {};
  }
  const values: Record<string, string> = {};
  for (const line of readFileSync(envFile, "utf8").split(/\r?\n/)) {
    const assignment = parseEnvLine(line);
    if (assignment) {
      values[assignment.key] = assignment.value;
    }
  }
  return values;
}

export function writeEnvValues(
  envFile: string,
  updates: Record<string, string>,
): void {
  const normalizedUpdates: Record<string, string> = {};
  for (const [key, value] of Object.entries(updates)) {
    normalizedUpdates[validateEnvKey(key)] = String(value);
  }
  for (const [key, value] of Object.entries(normalizedUpdates)) {
    if (value.includes("\n") || value.includes("\r")) {
      throw new Error(`Environment value for ${key} cannot contain newlines.`);
    }
  }

  mkdirSync(dirname(envFile), { recursive: true });
  const content = existsSync(envFile) ? readFileSync(envFile, "utf8") : "";
  const lines = content ? content.split(/(?<=\n)/) : [];
  const seen = new Set<string>();
  const rewritten: string[] = [];

  for (const rawLine of lines) {
    const line = rawLine.replace(/\r?\n$/, "");
    const newline = rawLine.endsWith("\n") ? rawLine.match(/\r?\n$/)?.[0] : "";
    const match = ENV_ASSIGNMENT_PATTERN.exec(line);
    if (match) {
      const prefix = match[1] ?? "";
      const key = match[2] ?? "";
      const separator = match[3] ?? "=";
      const value = normalizedUpdates[key];
      if (value === undefined) {
        rewritten.push(newline ? rawLine : `${rawLine}\n`);
        continue;
      }
      rewritten.push(
        `${prefix}${key}${separator}${formatEnvValue(value)}${newline || "\n"}`,
      );
      seen.add(key);
      continue;
    }
    rewritten.push(newline ? rawLine : `${rawLine}\n`);
  }

  const missing = Object.keys(normalizedUpdates).filter(
    (key) => !seen.has(key),
  );
  if (missing.length > 0 && rewritten.length > 0 && rewritten.at(-1)?.trim()) {
    rewritten.push("\n");
  }
  for (const key of missing) {
    rewritten.push(`${key}=${formatEnvValue(normalizedUpdates[key] ?? "")}\n`);
  }

  writeFileSync(envFile, rewritten.join(""), "utf8");
}

export function parseEnvAssignment(rawAssignment: string): EnvAssignment {
  if (!rawAssignment.includes("=")) {
    throw new Error(
      `Expected KEY=VALUE, got ${JSON.stringify(rawAssignment)}.`,
    );
  }
  const [rawKey, ...valueParts] = rawAssignment.split("=");
  return {
    key: validateEnvKey((rawKey ?? "").trim()),
    value: valueParts.join("="),
  };
}

export function validateEnvKey(key: string): string {
  if (!ENV_KEY_PATTERN.test(key)) {
    throw new Error(
      `Invalid environment variable name: ${JSON.stringify(key)}.`,
    );
  }
  return key;
}

export function llmProfileKey(profile: string, field: string): string {
  const normalizedProfile = profile.toLowerCase().replaceAll("-", "_");
  const normalizedField = field.toUpperCase();
  if (!isLlmProfileName(normalizedProfile)) {
    throw new Error(`Unsupported LLM profile: ${profile}`);
  }
  if (normalizedProfile === "default") {
    return `CODEWIKI_LLM__DEFAULT__${normalizedField}`;
  }
  return `CODEWIKI_LLM__PROFILES__${normalizedProfile.toUpperCase()}__${normalizedField}`;
}

export function codewikiValues(
  values: Record<string, string>,
): Record<string, string> {
  const rank = new Map<string, number>(
    COMMON_CONFIG_KEYS.map((key, index) => [key, index]),
  );
  return Object.fromEntries(
    Object.entries(values)
      .filter(([key]) => key.startsWith("CODEWIKI_"))
      .sort(([left], [right]) => {
        const leftRank = rank.get(left) ?? COMMON_CONFIG_KEYS.length;
        const rightRank = rank.get(right) ?? COMMON_CONFIG_KEYS.length;
        return leftRank - rightRank || left.localeCompare(right);
      }),
  );
}

export function maskConfigValues(
  values: Record<string, string>,
  options: { showSecrets?: boolean | undefined } = {},
): Record<string, string> {
  return Object.fromEntries(
    Object.entries(values).map(([key, value]) => [
      key,
      maskValue(key, value, options),
    ]),
  );
}

export function maskValue(
  key: string,
  value: string,
  options: { showSecrets?: boolean | undefined } = {},
): string {
  if (!value || options.showSecrets || !isSecretKey(key)) {
    return value;
  }
  return "********";
}

export function isSecretKey(key: string): boolean {
  const upper = key.toUpperCase();
  return SECRET_KEY_PARTS.some((part) => upper.includes(part));
}

export function formatEnvValue(value: string): string {
  return PLAIN_VALUE_PATTERN.test(value) ? value : JSON.stringify(value);
}

function parseEnvLine(line: string): EnvAssignment | null {
  const match = ENV_ASSIGNMENT_PATTERN.exec(line);
  if (!match) {
    return null;
  }
  return {
    key: match[2] ?? "",
    value: parseEnvValue(match[4] ?? ""),
  };
}

function parseEnvValue(rawValue: string): string {
  const value = rawValue.trim();
  if (!value) {
    return "";
  }
  if (value.startsWith('"')) {
    return parseDoubleQuotedValue(value);
  }
  if (value.startsWith("'")) {
    const end = value.indexOf("'", 1);
    return end === -1 ? value.slice(1) : value.slice(1, end);
  }
  return stripInlineComment(value).trim();
}

function parseDoubleQuotedValue(value: string): string {
  let escaped = false;
  for (let index = 1; index < value.length; index += 1) {
    const char = value[index];
    if (char === "\\" && !escaped) {
      escaped = true;
      continue;
    }
    if (char === '"' && !escaped) {
      const quoted = value.slice(0, index + 1);
      try {
        return JSON.parse(quoted) as string;
      } catch {
        return quoted.slice(1, -1);
      }
    }
    escaped = false;
  }
  return value.slice(1);
}

function stripInlineComment(value: string): string {
  const commentIndex = value.search(/\s#/);
  return commentIndex === -1 ? value : value.slice(0, commentIndex);
}

function isLlmProfileName(value: string): value is LlmProfileName {
  return LLM_PROFILES.includes(value as LlmProfileName);
}
