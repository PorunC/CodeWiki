import { createRequire } from "node:module";
import type { DatabaseSync } from "node:sqlite";

type StatementResult = { changes: number; lastInsertRowid: number | bigint };
type NamedParameters = Record<string, unknown>;
type SqliteModule = {
  DatabaseSync: typeof DatabaseSync;
};

export type CodeWikiSqliteStatement = {
  all(...anonymousParameters: unknown[]): Record<string, unknown>[];
  all(
    namedParameters: NamedParameters,
    ...anonymousParameters: unknown[]
  ): Record<string, unknown>[];
  get(...anonymousParameters: unknown[]): Record<string, unknown> | undefined;
  get(
    namedParameters: NamedParameters,
    ...anonymousParameters: unknown[]
  ): Record<string, unknown> | undefined;
  run(...anonymousParameters: unknown[]): StatementResult;
  run(
    namedParameters: NamedParameters,
    ...anonymousParameters: unknown[]
  ): StatementResult;
};

export class CodeWikiSqliteDatabase {
  private readonly db: DatabaseSync;

  constructor(readonly databasePath: string) {
    this.db = new (sqliteModule().DatabaseSync)(databasePath, {
      enableForeignKeyConstraints: true,
    });
  }

  exec(sql: string): void {
    this.db.exec(sql);
  }

  prepare(sql: string): CodeWikiSqliteStatement {
    const statement = this.db.prepare(sql);
    statement.setAllowBareNamedParameters(true);
    statement.setAllowUnknownNamedParameters(true);
    return statement as unknown as CodeWikiSqliteStatement;
  }

  pragma(
    command: string,
  ): Record<string, unknown> | Record<string, unknown>[] | undefined {
    const sql = command.trim().toLowerCase().startsWith("pragma")
      ? command.trim()
      : `PRAGMA ${command.trim()}`;
    const statement = this.prepare(sql);
    return sql.includes("=") ? statement.get() : statement.all();
  }

  transaction<TArgs extends unknown[], TResult>(
    fn: (...args: TArgs) => TResult,
  ): (...args: TArgs) => TResult {
    return (...args: TArgs): TResult => {
      this.exec("BEGIN IMMEDIATE");
      try {
        const result = fn(...args);
        this.exec("COMMIT");
        return result;
      } catch (error) {
        this.exec("ROLLBACK");
        throw error;
      }
    };
  }

  close(): void {
    this.db.close();
  }
}

let cachedSqliteModule: SqliteModule | null = null;

function sqliteModule(): SqliteModule {
  if (cachedSqliteModule) {
    return cachedSqliteModule;
  }
  const originalEmitWarning = process.emitWarning.bind(process);
  process.emitWarning = function emitWarningWithoutSqliteNoise(
    warning: string | Error,
    ...args: Parameters<typeof process.emitWarning> extends [
      string | Error,
      ...infer Rest,
    ]
      ? Rest
      : never
  ): void {
    const message =
      typeof warning === "string" ? warning : (warning.message ?? "");
    const warningType = typeof args[0] === "string" ? args[0] : undefined;
    if (warningType === "ExperimentalWarning" && message.includes("SQLite")) {
      return;
    }
    originalEmitWarning(warning, ...args);
  } as typeof process.emitWarning;
  try {
    const require = createRequire(import.meta.url);
    cachedSqliteModule = require("node:sqlite") as SqliteModule;
    return cachedSqliteModule;
  } finally {
    process.emitWarning = originalEmitWarning;
  }
}
