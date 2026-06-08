import type { CodeWikiSqliteDatabase } from "./sqlite.js";
import { randomUUID } from "node:crypto";
import type { AnalysisRun, JsonObject } from "../types.js";
import {
  analysisRunFromRow,
  isoNow,
  stringifyJson,
  type Row,
} from "./mappers.js";

export class AnalysisRunRepository {
  constructor(private readonly db: CodeWikiSqliteDatabase) {}

  createAnalysisRun(repoId: string): AnalysisRun {
    const run: AnalysisRun = {
      id: randomUUID(),
      repo_id: repoId,
      status: "running",
      started_at: isoNow(),
      finished_at: null,
      error: null,
      stats: {},
    };
    this.db
      .prepare(
        `
        INSERT INTO analysis_run (id, repo_id, status, started_at, finished_at, error, stats_json)
        VALUES (@id, @repo_id, @status, @started_at, @finished_at, @error, @stats_json)
        `,
      )
      .run({ ...run, stats_json: stringifyJson(run.stats) });
    return run;
  }

  finishAnalysisRun(
    runId: string,
    options: { status: string; stats: JsonObject; error?: string | null },
  ): AnalysisRun {
    this.db
      .prepare(
        `
        UPDATE analysis_run
        SET status = @status,
            finished_at = @finished_at,
            error = @error,
            stats_json = @stats_json
        WHERE id = @id
        `,
      )
      .run({
        id: runId,
        status: options.status,
        finished_at: isoNow(),
        error: options.error ?? null,
        stats_json: stringifyJson(options.stats),
      });
    const run = this.getAnalysisRun(runId);
    if (!run) {
      throw new Error(`Analysis run not found: ${runId}`);
    }
    return run;
  }

  updateAnalysisRunStats(runId: string, stats: JsonObject): void {
    this.db
      .prepare(
        "UPDATE analysis_run SET stats_json = @stats_json WHERE id = @id",
      )
      .run({ id: runId, stats_json: stringifyJson(stats) });
  }

  listAnalysisRuns(repoId: string): AnalysisRun[] {
    return (
      this.db
        .prepare(
          "SELECT * FROM analysis_run WHERE repo_id = ? ORDER BY started_at DESC",
        )
        .all(repoId) as Row[]
    ).map(analysisRunFromRow);
  }

  getAnalysisRun(runId: string): AnalysisRun | null {
    const row = this.db
      .prepare("SELECT * FROM analysis_run WHERE id = ?")
      .get(runId) as Row | undefined;
    return row ? analysisRunFromRow(row) : null;
  }
}
