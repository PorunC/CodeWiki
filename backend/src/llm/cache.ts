import { createHash } from "node:crypto";
import type { CodeWikiStoreApi } from "../db/types.js";
import type { JsonObject, JsonValue, LlmRun } from "../types.js";
import type {
  LlmCompletionOptions,
  LlmCompletionResult,
  LlmGateway,
  LlmMessage,
} from "./gateway.js";

export type LlmOperation = {
  taskType: string;
  messages: LlmMessage[];
  inputPayload: JsonObject;
  cacheKey: string;
  modelAlias?: string | undefined;
  promptVersion?: string | undefined;
  completion?: LlmCompletionOptions | undefined;
};

export type CachedLlmCompletion = {
  result: LlmCompletionResult;
  run: LlmRun;
  cacheHit: boolean;
};

export class LlmCallError extends Error {
  constructor(
    message: string,
    readonly taskType: string,
    readonly runId: string | null = null,
  ) {
    super(message);
    this.name = "LlmCallError";
  }
}

export class CachedLlmService {
  constructor(
    private readonly store: CodeWikiStoreApi,
    private readonly gateway: LlmGateway,
  ) {}

  isConfigured(taskType: string): boolean {
    return this.gateway.isConfigured(taskType);
  }

  async complete(
    repoId: string,
    operation: LlmOperation,
  ): Promise<CachedLlmCompletion> {
    const profile = this.gateway.profile(operation.taskType);
    const inputHash = payloadHash(operation.inputPayload);
    const cachedRun = this.store.getCachedLlmRun(repoId, {
      taskType: operation.taskType,
      cacheKey: operation.cacheKey,
      inputHash,
      model: profile.model,
      promptVersion: operation.promptVersion,
    });
    if (cachedRun) {
      const result: LlmCompletionResult = {
        content: cachedRun.response_content,
        model: cachedRun.model,
        provider: cachedRun.provider,
        usage: cachedRun.response_usage,
      };
      return {
        result,
        cacheHit: true,
        run: this.store.recordLlmRun(repoId, {
          taskType: operation.taskType,
          provider: cachedRun.provider,
          model: cachedRun.model,
          modelAlias: operation.modelAlias ?? cachedRun.model_alias,
          promptVersion: operation.promptVersion,
          inputHash,
          cacheKey: operation.cacheKey,
          tokensIn: cachedRun.tokens_in,
          tokensOut: cachedRun.tokens_out,
          costUsd: 0,
          durationMs: 0,
          responseContent: cachedRun.response_content,
          responseUsage: cachedRun.response_usage,
          cached: true,
        }),
      };
    }

    const startedAt = Date.now();
    try {
      const result = await this.gateway.complete(
        operation.taskType,
        operation.messages,
        {
          ...operation.completion,
          providerUserId:
            operation.completion?.providerUserId ??
            providerUserIdForRepo(repoId),
        },
      );
      const usage = normalizeUsage(result.usage);
      return {
        result: { ...result, usage },
        cacheHit: false,
        run: this.store.recordLlmRun(repoId, {
          taskType: operation.taskType,
          provider: result.provider,
          model: result.model,
          modelAlias: operation.modelAlias ?? operation.taskType,
          promptVersion: operation.promptVersion,
          inputHash,
          cacheKey: operation.cacheKey,
          tokensIn: tokenCount(usage, "prompt_tokens", "input_tokens"),
          tokensOut: tokenCount(usage, "completion_tokens", "output_tokens"),
          durationMs: Date.now() - startedAt,
          responseContent: result.content,
          responseUsage: usage,
          cached: false,
        }),
      };
    } catch (error) {
      const message = sanitizedErrorMessage(error);
      const run = this.store.recordLlmRun(repoId, {
        taskType: operation.taskType,
        provider: profile.provider_type ?? modelProvider(profile.model),
        model: profile.model,
        modelAlias: operation.modelAlias ?? operation.taskType,
        promptVersion: operation.promptVersion,
        inputHash,
        cacheKey: operation.cacheKey,
        durationMs: Date.now() - startedAt,
        status: "error",
        error: message,
      });
      throw new LlmCallError(message, operation.taskType, run.id);
    }
  }
}

export function providerUserIdForRepo(repoId: string): string {
  const normalized = repoId
    .replace(/[^A-Za-z0-9_-]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return `codewiki-${normalized || "repo"}`.slice(0, 512);
}

export function payloadHash(payload: JsonObject): string {
  return createHash("sha256").update(stableJson(payload)).digest("hex");
}

function normalizeUsage(usage: JsonObject): JsonObject {
  return Object.fromEntries(
    Object.entries(usage).filter(([, value]) => isJsonValue(value)),
  );
}

function tokenCount(usage: JsonObject, ...keys: string[]): number {
  for (const key of keys) {
    const value = usage[key];
    if (typeof value === "number" && Number.isFinite(value)) {
      return Math.max(0, Math.trunc(value));
    }
  }
  return 0;
}

function stableJson(value: JsonValue): string {
  if (Array.isArray(value)) {
    return `[${value.map(stableJson).join(",")}]`;
  }
  if (value && typeof value === "object") {
    return `{${Object.entries(value)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, nested]) => `${JSON.stringify(key)}:${stableJson(nested)}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

function sanitizedErrorMessage(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error);
  return message
    .replace(/sk-[A-Za-z0-9_-]{8,}/g, "sk-[REDACTED]")
    .replace(/(api[_-]?key\s*[:=]\s*)\S+/gi, "$1[REDACTED]")
    .replace(/(authorization\s*[:=]\s*bearer\s+)\S+/gi, "$1[REDACTED]")
    .slice(0, 1600);
}

function modelProvider(model: string): string | null {
  const [provider] = model.split("/", 1);
  return model.includes("/") && provider ? provider : null;
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
  if (typeof value === "object" && value !== null) {
    return Object.values(value).every(isJsonValue);
  }
  return false;
}
