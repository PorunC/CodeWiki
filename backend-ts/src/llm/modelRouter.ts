import type { CodeWikiSettings, LlmProfileSettings } from "../config.js";

export type LlmTaskType =
  | "catalog"
  | "community_summary"
  | "cluster"
  | "page"
  | "translation"
  | "qa"
  | "embedding";

export type ResolvedLlmProfile = {
  task_type: string;
  model: string;
  provider_type: string | null;
  endpoint: string | null;
  api_key: string | null;
  max_tokens: number | null;
  stream: boolean;
};

export type LlmConfigurationTestRequest = {
  taskType?: string | undefined;
  model?: string | undefined;
};

export type LlmConfigurationTestResult = {
  status: "configured" | "missing_model" | "missing_credentials";
  configured: boolean;
  task_type: string;
  model: string;
  provider_type: string;
  endpoint: string;
  has_api_key: boolean;
  stream: boolean;
  max_tokens: number | null;
  message: string;
};

type TaskRoutingDefault = {
  maxTokens: number | null;
  stream: boolean;
  profileKey?: LlmTaskType;
};

export const FALLBACK_MODEL = "provider/strong-coding-model";
const TASK_ROUTING_DEFAULTS: Record<LlmTaskType, TaskRoutingDefault> = {
  catalog: { maxTokens: 4096, stream: false },
  community_summary: { maxTokens: 4096, stream: false },
  cluster: {
    maxTokens: 4096,
    stream: false,
    profileKey: "community_summary",
  },
  page: { maxTokens: 12000, stream: false },
  translation: { maxTokens: 12000, stream: false },
  qa: { maxTokens: null, stream: true },
  embedding: { maxTokens: null, stream: false },
};

export const LLM_TASK_TYPES = Object.keys(
  TASK_ROUTING_DEFAULTS,
) as LlmTaskType[];

export function profileForTask(
  settings: CodeWikiSettings,
  taskType: string,
): ResolvedLlmProfile {
  if (!isLlmTaskType(taskType)) {
    throw new Error(`Unsupported LLM task type: ${taskType}`);
  }
  const defaults = TASK_ROUTING_DEFAULTS[taskType];
  const configured = configuredProfile(settings, taskType);
  const fallback = defaults.profileKey
    ? configuredProfile(settings, defaults.profileKey)
    : emptyProfile();
  return {
    task_type: taskType,
    model:
      value(configured.model, fallback.model, settings.llm.default.model) ??
      FALLBACK_MODEL,
    provider_type: value(
      configured.provider_type,
      fallback.provider_type,
      settings.llm.default.provider_type,
    ),
    endpoint: value(
      configured.endpoint,
      fallback.endpoint,
      settings.llm.default.endpoint,
    ),
    api_key: value(
      configured.api_key,
      fallback.api_key,
      settings.llm.default.api_key,
    ),
    max_tokens: maxTokens(
      configured,
      fallback,
      settings.llm.default,
      defaults.maxTokens,
    ),
    stream: defaults.stream,
  };
}

export function defaultLlmProfile(
  settings: CodeWikiSettings,
): ResolvedLlmProfile {
  return {
    task_type: "default",
    model: value(settings.llm.default.model) ?? FALLBACK_MODEL,
    provider_type: value(settings.llm.default.provider_type),
    endpoint: value(settings.llm.default.endpoint),
    api_key: value(settings.llm.default.api_key),
    max_tokens: settings.llm.default.max_tokens,
    stream: false,
  };
}

export function llmTaskProfiles(
  settings: CodeWikiSettings,
): Record<string, ResolvedLlmProfile> {
  return Object.fromEntries(
    LLM_TASK_TYPES.map((taskType) => [
      taskType,
      profileForTask(settings, taskType),
    ]),
  );
}

export function testLlmConfiguration(
  settings: CodeWikiSettings,
  request: LlmConfigurationTestRequest = {},
): LlmConfigurationTestResult {
  const taskType = request.taskType?.trim() || "qa";
  const profile = profileForTask(settings, taskType);
  const model = request.model?.trim() || profile.model;
  const testedProfile = { ...profile, model };
  const common = {
    task_type: taskType,
    model,
    provider_type: testedProfile.provider_type ?? "",
    endpoint: testedProfile.endpoint ?? "",
    has_api_key: Boolean(testedProfile.api_key),
    stream: testedProfile.stream,
    max_tokens: testedProfile.max_tokens,
  };

  if (!model) {
    return {
      ...common,
      status: "missing_model",
      configured: false,
      message: "No model is configured for this task.",
    };
  }
  if (requiresCredentials(testedProfile) && !testedProfile.api_key) {
    return {
      ...common,
      status: "missing_credentials",
      configured: false,
      message:
        "Model routing is configured, but no API key or local endpoint is available.",
    };
  }
  return {
    ...common,
    status: "configured",
    configured: true,
    message:
      "LLM routing is configured. Provider calls are not executed by this offline check.",
  };
}

function isLlmTaskType(taskType: string): taskType is LlmTaskType {
  return Object.hasOwn(TASK_ROUTING_DEFAULTS, taskType);
}

function configuredProfile(
  settings: CodeWikiSettings,
  taskType: LlmTaskType,
): LlmProfileSettings {
  return settings.llm.profiles[taskType] ?? emptyProfile();
}

function emptyProfile(): LlmProfileSettings {
  return {
    model: null,
    provider_type: null,
    endpoint: null,
    api_key: null,
    max_tokens: null,
  };
}

function value(...values: Array<string | null | undefined>): string | null {
  for (const item of values) {
    const trimmed = item?.trim();
    if (trimmed) {
      return trimmed;
    }
  }
  return null;
}

function maxTokens(
  profile: LlmProfileSettings,
  fallback: LlmProfileSettings,
  defaultProfile: LlmProfileSettings,
  taskDefault: number | null,
): number | null {
  for (const value of [
    profile.max_tokens,
    fallback.max_tokens,
    defaultProfile.max_tokens,
    taskDefault,
  ]) {
    if (typeof value === "number" && value > 0) {
      return value;
    }
  }
  return null;
}

function requiresCredentials(profile: ResolvedLlmProfile): boolean {
  if (profile.api_key) {
    return false;
  }
  const provider = profile.provider_type?.toLowerCase() ?? "";
  const model = profile.model.toLowerCase();
  const endpoint = profile.endpoint?.toLowerCase() ?? "";
  if (
    ["local", "ollama", "lmstudio"].includes(provider) ||
    endpoint.includes("localhost") ||
    endpoint.includes("127.0.0.1")
  ) {
    return false;
  }
  if (endpoint && !provider) {
    return false;
  }
  return /^(?:openai|anthropic|deepseek|gemini|google|azure|provider)\//.test(
    model,
  );
}
