import type { CodeWikiSqliteDatabase } from "./sqlite.js";
import { randomUUID } from "node:crypto";
import type { JsonObject, LlmRun } from "../types.js";
import { isoNow, llmRunFromRow, stringifyJson, type Row } from "./mappers.js";

export type RecordLlmRunInput = {
  taskType: string;
  model: string;
  inputHash: string;
  cacheKey: string;
  provider?: string | null | undefined;
  modelAlias?: string | null | undefined;
  promptVersion?: string | null | undefined;
  tokensIn?: number | undefined;
  tokensOut?: number | undefined;
  costUsd?: number | null | undefined;
  durationMs?: number | null | undefined;
  responseContent?: string | undefined;
  responseUsage?: JsonObject | undefined;
  cached?: boolean | undefined;
  status?: string | undefined;
  error?: string | null | undefined;
};

export type CachedLlmRunQuery = {
  taskType: string;
  cacheKey: string;
  inputHash: string;
  model?: string | null | undefined;
  promptVersion?: string | null | undefined;
};

export type ListLlmRunsOptions = {
  taskType?: string | undefined;
};

export class LlmRunRepository {
  constructor(private readonly db: CodeWikiSqliteDatabase) {}

  recordLlmRun(repoId: string, input: RecordLlmRunInput): LlmRun {
    const run = {
      id: randomUUID(),
      repo_id: repoId,
      task_type: input.taskType,
      provider: input.provider ?? null,
      model: input.model,
      model_alias: input.modelAlias ?? null,
      prompt_version: input.promptVersion ?? null,
      input_hash: input.inputHash,
      cache_key: input.cacheKey,
      tokens_in: input.tokensIn ?? 0,
      tokens_out: input.tokensOut ?? 0,
      cost_usd: input.costUsd ?? null,
      duration_ms: input.durationMs ?? null,
      response_content: input.responseContent ?? "",
      response_usage: input.responseUsage ?? {},
      cached: input.cached ?? false,
      status: input.status ?? "success",
      error: input.error ?? null,
      created_at: isoNow(),
    } satisfies LlmRun;

    this.db
      .prepare(
        `
        INSERT INTO llm_run (
          id, repo_id, task_type, provider, model, model_alias, prompt_version,
          input_hash, cache_key, tokens_in, tokens_out, cost_usd, duration_ms,
          response_content, response_usage_json, cached, status, error, created_at
        )
        VALUES (
          @id, @repo_id, @task_type, @provider, @model, @model_alias, @prompt_version,
          @input_hash, @cache_key, @tokens_in, @tokens_out, @cost_usd, @duration_ms,
          @response_content, @response_usage_json, @cached, @status, @error, @created_at
        )
        `,
      )
      .run({
        ...run,
        response_usage_json: stringifyJson(run.response_usage),
        cached: run.cached ? 1 : 0,
      });
    return run;
  }

  getCachedLlmRun(repoId: string, query: CachedLlmRunQuery): LlmRun | null {
    const conditions = [
      "repo_id = @repo_id",
      "task_type = @task_type",
      "cache_key = @cache_key",
      "input_hash = @input_hash",
      "status = 'success'",
      "response_content != ''",
    ];
    const params: Record<string, string> = {
      repo_id: repoId,
      task_type: query.taskType,
      cache_key: query.cacheKey,
      input_hash: query.inputHash,
    };
    if (query.model) {
      conditions.push("model = @model");
      params.model = query.model;
    }
    if (query.promptVersion) {
      conditions.push("prompt_version = @prompt_version");
      params.prompt_version = query.promptVersion;
    }
    const row = this.db
      .prepare(
        `
        SELECT * FROM llm_run
        WHERE ${conditions.join(" AND ")}
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        `,
      )
      .get(params) as Row | undefined;
    return row ? llmRunFromRow(row) : null;
  }

  updateLlmRunStatus(
    runId: string,
    options: { status: string; error?: string | null | undefined },
  ): LlmRun | null {
    this.db
      .prepare(
        `
        UPDATE llm_run
        SET status = @status, error = @error
        WHERE id = @id
        `,
      )
      .run({
        id: runId,
        status: options.status,
        error: options.error ?? null,
      });
    return this.getLlmRun(runId);
  }

  listLlmRuns(repoId: string, options: ListLlmRunsOptions = {}): LlmRun[] {
    if (options.taskType) {
      return (
        this.db
          .prepare(
            `
            SELECT * FROM llm_run
            WHERE repo_id = ? AND task_type = ?
            ORDER BY created_at DESC, id DESC
            `,
          )
          .all(repoId, options.taskType) as Row[]
      ).map(llmRunFromRow);
    }
    return (
      this.db
        .prepare(
          `
          SELECT * FROM llm_run
          WHERE repo_id = ?
          ORDER BY created_at DESC, id DESC
          `,
        )
        .all(repoId) as Row[]
    ).map(llmRunFromRow);
  }

  private getLlmRun(runId: string): LlmRun | null {
    const row = this.db
      .prepare("SELECT * FROM llm_run WHERE id = ?")
      .get(runId) as Row | undefined;
    return row ? llmRunFromRow(row) : null;
  }
}
