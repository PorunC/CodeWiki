import type Database from "better-sqlite3";
import type { RetrievalTrace } from "../types.js";
import { isoNow, retrievalTraceFromRow, type Row } from "./mappers.js";

export class RetrievalTraceRepository {
  constructor(private readonly db: Database.Database) {}

  saveRetrievalTrace(trace: RetrievalTrace): RetrievalTrace {
    const saved = {
      ...trace,
      created_at: trace.created_at ?? isoNow(),
    };
    this.db
      .prepare(
        `
        INSERT INTO graphrag_trace (id, repo_id, query, max_hops, payload_json, created_at)
        VALUES (@id, @repo_id, @query, @max_hops, @payload_json, @created_at)
        ON CONFLICT(id) DO UPDATE SET
          repo_id = excluded.repo_id,
          query = excluded.query,
          max_hops = excluded.max_hops,
          payload_json = excluded.payload_json,
          created_at = excluded.created_at
        `,
      )
      .run({
        id: saved.trace_id,
        repo_id: saved.repo_id,
        query: saved.query,
        max_hops: saved.max_hops,
        payload_json: JSON.stringify(saved),
        created_at: saved.created_at,
      });
    return saved;
  }

  getRetrievalTrace(repoId: string, traceId: string): RetrievalTrace | null {
    const row = this.db
      .prepare("SELECT * FROM graphrag_trace WHERE repo_id = ? AND id = ?")
      .get(repoId, traceId) as Row | undefined;
    return row ? retrievalTraceFromRow(row) : null;
  }
}
