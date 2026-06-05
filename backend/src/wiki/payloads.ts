import type { DocCatalog, DocPage, JsonObject, LlmRun } from "../types.js";

export type WikiCatalogResult = {
  catalog: DocCatalog;
  validation_errors: string[];
  llm?: JsonObject | undefined;
};

export type WikiPageResult = {
  page: DocPage;
  validation_errors: string[];
  llm?: JsonObject | undefined;
};

export function catalogPayload(catalog: DocCatalog): JsonObject {
  return {
    id: catalog.id,
    repo_id: catalog.repo_id,
    language_code: catalog.language_code,
    title: catalog.title,
    structure: catalog.structure,
    generated_at: catalog.generated_at,
  };
}

export function catalogResultPayload(result: WikiCatalogResult): JsonObject {
  return {
    ...catalogPayload(result.catalog),
    validation_errors: result.validation_errors,
    ...(result.llm ? { llm: result.llm } : {}),
  };
}

export function pagePayload(page: DocPage): JsonObject {
  return {
    id: page.id,
    repo_id: page.repo_id,
    language_code: page.language_code,
    slug: page.slug,
    title: page.title,
    parent_slug: page.parent_slug,
    markdown: page.markdown,
    source_refs: page.source_refs,
    graph_refs: page.graph_refs,
    status: page.status,
    updated_at: page.updated_at,
  };
}

export function pageResultPayload(result: WikiPageResult): JsonObject {
  return {
    ...pagePayload(result.page),
    validation_errors: result.validation_errors,
    ...(result.llm ? { llm: result.llm } : {}),
  };
}

export function llmCachePayload(runs: LlmRun[] = []): JsonObject {
  let promptTokens = 0;
  let hitTokens = 0;
  let missTokens = 0;
  let localCacheHits = 0;
  let providerMeasuredRuns = 0;
  for (const run of runs) {
    if (run.cached) {
      localCacheHits += 1;
      continue;
    }
    promptTokens += usageInt(
      run.response_usage,
      "prompt_tokens",
      "input_tokens",
      "prompt_eval_count",
    );
    const hit = usageInt(run.response_usage, "prompt_cache_hit_tokens");
    const miss = usageInt(run.response_usage, "prompt_cache_miss_tokens");
    if (hit || miss) {
      providerMeasuredRuns += 1;
    }
    hitTokens += hit;
    missTokens += miss;
  }
  const cacheTotal = hitTokens + missTokens;
  return {
    run_count: runs.length,
    prompt_tokens: promptTokens,
    prompt_cache_hit_tokens: hitTokens,
    prompt_cache_miss_tokens: missTokens,
    prompt_cache_hit_ratio: cacheTotal ? hitTokens / cacheTotal : null,
    local_cache_hits: localCacheHits,
    provider_measured_runs: providerMeasuredRuns,
  };
}

export function llmCachePayloadForTasks(
  runsByTask: (taskType: string) => LlmRun[],
  taskTypes: string[],
): JsonObject {
  return llmCachePayload(taskTypes.flatMap((taskType) => runsByTask(taskType)));
}

function usageInt(usage: JsonObject, ...keys: string[]): number {
  for (const key of keys) {
    const value = usage[key];
    if (typeof value === "number" && Number.isFinite(value)) {
      return Math.trunc(value);
    }
  }
  return 0;
}
