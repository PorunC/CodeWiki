import type { CodeWikiSettings } from "../config.js";
import type { JsonObject } from "../types.js";
import {
  FALLBACK_MODEL,
  profileForTask,
  type ResolvedLlmProfile,
} from "./modelRouter.js";

export type LlmMessage = {
  role: "system" | "user" | "assistant";
  content: string;
};

export type LlmCompletionOptions = {
  responseFormat?: string | undefined;
  providerUserId?: string | undefined;
};

export type LlmCompletionResult = {
  content: string;
  model: string;
  provider: string | null;
  usage: JsonObject;
};

export type LlmEmbeddingOptions = {
  providerUserId?: string | undefined;
};

export type LlmEmbeddingResult = {
  embeddings: number[][];
  model: string;
  provider: string | null;
  usage: JsonObject;
};

export type LlmGateway = {
  isConfigured(taskType: string): boolean;
  profile(taskType: string): ResolvedLlmProfile;
  complete(
    taskType: string,
    messages: LlmMessage[],
    options?: LlmCompletionOptions,
  ): Promise<LlmCompletionResult>;
};

export type LlmEmbeddingGateway = {
  isConfigured(taskType: string): boolean;
  profile(taskType: string): ResolvedLlmProfile;
  embed(
    taskType: string,
    texts: string[],
    options?: LlmEmbeddingOptions,
  ): Promise<LlmEmbeddingResult>;
};

type FetchResponseLike = {
  ok: boolean;
  status: number;
  text(): Promise<string>;
};

type FetchLike = (
  url: string,
  init: {
    method: "POST";
    headers: Record<string, string>;
    body: string;
    signal?: AbortSignal | undefined;
  },
) => Promise<FetchResponseLike>;

const DEFAULT_TIMEOUT_MS = 60_000;
const OPENAI_CHAT_COMPLETIONS_URL =
  "https://api.openai.com/v1/chat/completions";
const OPENAI_EMBEDDINGS_URL = "https://api.openai.com/v1/embeddings";
const DEEPSEEK_CHAT_COMPLETIONS_URL =
  "https://api.deepseek.com/v1/chat/completions";
const DEEPSEEK_EMBEDDINGS_URL = "https://api.deepseek.com/v1/embeddings";

export class OpenAiCompatibleLlmGateway implements LlmGateway {
  private readonly fetchImpl: FetchLike;

  constructor(
    private readonly settings: CodeWikiSettings,
    options: { fetch?: FetchLike | undefined } = {},
  ) {
    this.fetchImpl = options.fetch ?? defaultFetch;
  }

  isConfigured(taskType: string): boolean {
    return isOpenAiCompatibleProfile(this.profile(taskType));
  }

  profile(taskType: string): ResolvedLlmProfile {
    return profileForTask(this.settings, taskType);
  }

  async complete(
    taskType: string,
    messages: LlmMessage[],
    options: LlmCompletionOptions = {},
  ): Promise<LlmCompletionResult> {
    const profile = this.profile(taskType);
    if (!isOpenAiCompatibleProfile(profile)) {
      throw new Error(
        `LLM task '${taskType}' is not configured for an OpenAI-compatible completion endpoint.`,
      );
    }

    const body: JsonObject = {
      model: providerModelName(profile),
      messages,
      temperature: 0.1,
      stream: false,
    };
    if (typeof profile.max_tokens === "number" && profile.max_tokens > 0) {
      body.max_tokens = profile.max_tokens;
    }
    if (options.responseFormat) {
      body.response_format = { type: options.responseFormat };
    }
    if (options.providerUserId && isDeepSeekProfile(profile)) {
      body.user_id = options.providerUserId;
    }

    const headers: Record<string, string> = {
      "content-type": "application/json",
    };
    if (profile.api_key) {
      headers.authorization = `Bearer ${profile.api_key}`;
    }

    const response = await this.fetchImpl(completionEndpoint(profile), {
      method: "POST",
      headers,
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(DEFAULT_TIMEOUT_MS),
    });
    const text = await response.text();
    if (!response.ok) {
      throw new Error(
        `LLM completion failed with HTTP ${response.status}: ${sanitizeProviderText(text)}`,
      );
    }

    const payload = parseProviderJson(text);
    return {
      content: completionContent(payload),
      model: profile.model,
      provider: providerName(profile),
      usage: completionUsage(payload),
    };
  }

  async embed(
    taskType: string,
    texts: string[],
    options: LlmEmbeddingOptions = {},
  ): Promise<LlmEmbeddingResult> {
    const profile = this.profile(taskType);
    if (!isOpenAiCompatibleProfile(profile)) {
      throw new Error(
        `LLM task '${taskType}' is not configured for an OpenAI-compatible embeddings endpoint.`,
      );
    }

    const body: JsonObject = {
      model: providerModelName(profile),
      input: texts,
    };
    if (options.providerUserId) {
      body[isDeepSeekProfile(profile) ? "user_id" : "user"] =
        options.providerUserId;
    }

    const headers: Record<string, string> = {
      "content-type": "application/json",
    };
    if (profile.api_key) {
      headers.authorization = `Bearer ${profile.api_key}`;
    }

    const response = await this.fetchImpl(embeddingEndpoint(profile), {
      method: "POST",
      headers,
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(DEFAULT_TIMEOUT_MS),
    });
    const text = await response.text();
    if (!response.ok) {
      throw new Error(
        `LLM embedding failed with HTTP ${response.status}: ${sanitizeProviderText(text)}`,
      );
    }

    const payload = parseProviderJson(text);
    return {
      embeddings: embeddingVectors(payload),
      model: profile.model,
      provider: providerName(profile),
      usage: completionUsage(payload),
    };
  }
}

export function isOpenAiCompatibleProfile(
  profile: ResolvedLlmProfile,
): boolean {
  if (!profile.model || profile.model === FALLBACK_MODEL) {
    return false;
  }
  if (profile.endpoint) {
    return true;
  }
  if (!profile.api_key) {
    return false;
  }
  const provider = providerName(profile);
  if (!provider) {
    return true;
  }
  return ["openai", "deepseek"].includes(provider);
}

function completionEndpoint(profile: ResolvedLlmProfile): string {
  const endpoint = profile.endpoint?.trim();
  if (endpoint) {
    return endpoint.endsWith("/chat/completions")
      ? endpoint
      : `${endpoint.replace(/\/+$/, "")}/chat/completions`;
  }
  return isDeepSeekProfile(profile)
    ? DEEPSEEK_CHAT_COMPLETIONS_URL
    : OPENAI_CHAT_COMPLETIONS_URL;
}

function embeddingEndpoint(profile: ResolvedLlmProfile): string {
  const endpoint = profile.endpoint?.trim();
  if (endpoint) {
    if (endpoint.endsWith("/embeddings")) {
      return endpoint;
    }
    if (endpoint.endsWith("/chat/completions")) {
      return endpoint.replace(/\/chat\/completions$/, "/embeddings");
    }
    return `${endpoint.replace(/\/+$/, "")}/embeddings`;
  }
  return isDeepSeekProfile(profile)
    ? DEEPSEEK_EMBEDDINGS_URL
    : OPENAI_EMBEDDINGS_URL;
}

function providerModelName(profile: ResolvedLlmProfile): string {
  const provider = providerName(profile);
  if (!provider || !profile.model.includes("/")) {
    return profile.model;
  }
  return ["openai", "deepseek"].includes(provider)
    ? profile.model.split("/").slice(1).join("/")
    : profile.model;
}

function providerName(profile: ResolvedLlmProfile): string | null {
  const configured = profile.provider_type?.trim().toLowerCase();
  if (configured) {
    return configured;
  }
  const [prefix] = profile.model.split("/", 1);
  return profile.model.includes("/") && prefix ? prefix.toLowerCase() : null;
}

function isDeepSeekProfile(profile: ResolvedLlmProfile): boolean {
  const provider = providerName(profile);
  const endpoint = profile.endpoint?.toLowerCase() ?? "";
  return (
    provider === "deepseek" ||
    profile.model.toLowerCase().startsWith("deepseek/") ||
    endpoint.includes("deepseek.com")
  );
}

function parseProviderJson(text: string): JsonObject {
  try {
    const parsed = JSON.parse(text) as unknown;
    if (isJsonObject(parsed)) {
      return parsed;
    }
  } catch {
    // Fall through to a stable error below.
  }
  throw new Error("LLM completion response was not a JSON object.");
}

function completionContent(payload: JsonObject): string {
  const choices = payload.choices;
  if (!Array.isArray(choices) || choices.length === 0) {
    throw new Error("LLM completion response did not include choices.");
  }
  const [firstChoice] = choices;
  if (!isJsonObject(firstChoice)) {
    throw new Error("LLM completion choice was not an object.");
  }
  const message = firstChoice.message;
  if (isJsonObject(message) && typeof message.content === "string") {
    return message.content;
  }
  if (typeof firstChoice.text === "string") {
    return firstChoice.text;
  }
  throw new Error("LLM completion choice did not include text content.");
}

function completionUsage(payload: JsonObject): JsonObject {
  return isJsonObject(payload.usage) ? payload.usage : {};
}

function embeddingVectors(payload: JsonObject): number[][] {
  const data = payload.data;
  if (!Array.isArray(data)) {
    throw new Error("LLM embedding response did not include data.");
  }
  const vectors = [...data]
    .sort((left, right) => embeddingIndex(left) - embeddingIndex(right))
    .map((item) => {
      if (!isJsonObject(item) || !Array.isArray(item.embedding)) {
        throw new Error(
          "LLM embedding item did not include an embedding vector.",
        );
      }
      const vector = item.embedding.filter(
        (value): value is number =>
          typeof value === "number" && Number.isFinite(value),
      );
      if (!vector.length) {
        throw new Error("LLM embedding item included an empty vector.");
      }
      return vector;
    });
  if (!vectors.length) {
    throw new Error("LLM embedding response did not include vectors.");
  }
  return vectors;
}

function embeddingIndex(value: unknown): number {
  return isJsonObject(value) && typeof value.index === "number"
    ? value.index
    : 0;
}

function sanitizeProviderText(text: string): string {
  return text
    .replace(/sk-[A-Za-z0-9_-]{8,}/g, "sk-[REDACTED]")
    .replace(/(api[_-]?key\s*[:=]\s*)\S+/gi, "$1[REDACTED]")
    .replace(/(authorization\s*[:=]\s*bearer\s+)\S+/gi, "$1[REDACTED]")
    .slice(0, 1600);
}

function isJsonObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

async function defaultFetch(
  url: string,
  init: {
    method: "POST";
    headers: Record<string, string>;
    body: string;
    signal?: AbortSignal | undefined;
  },
): Promise<FetchResponseLike> {
  const requestInit: RequestInit = {
    method: init.method,
    headers: init.headers,
    body: init.body,
  };
  if (init.signal) {
    requestInit.signal = init.signal;
  }
  return fetch(url, requestInit);
}
