import type Database from "better-sqlite3";
import type { RepoDescriptor } from "../types.js";
import { isoNow, repoFromRow, type Row } from "./mappers.js";

export class RepoRepository {
  constructor(private readonly db: Database.Database) {}

  upsertRepo(repo: RepoDescriptor): RepoDescriptor {
    const now = isoNow();
    const existing = this.getRepo(repo.id);
    this.db
      .prepare(
        `
        INSERT INTO repo (
          id, name, path, source_type, git_url, commit_hash, created_at, updated_at
        )
        VALUES (
          @id, @name, @path, @source_type, @git_url, @commit_hash, @created_at, @updated_at
        )
        ON CONFLICT(id) DO UPDATE SET
          name = excluded.name,
          path = excluded.path,
          source_type = excluded.source_type,
          git_url = excluded.git_url,
          commit_hash = excluded.commit_hash,
          updated_at = excluded.updated_at
        `,
      )
      .run({
        ...repo,
        created_at: repo.created_at ?? existing?.created_at ?? now,
        updated_at: now,
      });
    return (
      this.getRepo(repo.id) ?? { ...repo, created_at: now, updated_at: now }
    );
  }

  getRepo(repoId: string): RepoDescriptor | null {
    const row = this.db
      .prepare("SELECT * FROM repo WHERE id = ?")
      .get(repoId) as Row | undefined;
    return row ? repoFromRow(row) : null;
  }

  listRepos(): RepoDescriptor[] {
    return (
      this.db
        .prepare("SELECT * FROM repo ORDER BY updated_at DESC, name ASC")
        .all() as Row[]
    ).map(repoFromRow);
  }

  deleteRepo(repoId: string): boolean {
    const result = this.db.prepare("DELETE FROM repo WHERE id = ?").run(repoId);
    return result.changes > 0;
  }
}
