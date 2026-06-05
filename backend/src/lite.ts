import { existsSync, mkdirSync, rmSync } from "node:fs";
import { join, resolve } from "node:path";
import { getSettings, type CodeWikiSettings } from "./config.js";
import { CodeWikiStore } from "./db/store.js";
import { CodeWikiMCPServer } from "./mcp/server.js";
import { RepoScanner } from "./scanner/scanner.js";
import {
  createBackendRuntime,
  type BackendServices,
} from "./services/backendServices.js";
import type { RepoDescriptor } from "./types.js";

export const LITE_DIR_NAME = ".codewiki";
export const LITE_DB_NAME = "codewiki-lite.sqlite3";

export type LiteRepoOptions = {
  path?: string;
  name?: string;
  source_type?: string;
  env?: NodeJS.ProcessEnv;
};

export type LiteRepoContext = {
  settings: CodeWikiSettings;
  store: CodeWikiStore;
  scanner: RepoScanner;
  services: BackendServices;
  repo: RepoDescriptor;
  databasePath: string;
  liteDir: string;
};

export function liteRoot(path = "."): string {
  return resolve(expandHome(path));
}

export function liteDir(path = "."): string {
  return join(liteRoot(path), LITE_DIR_NAME);
}

export function liteDatabasePath(path = "."): string {
  return join(liteDir(path), LITE_DB_NAME);
}

export function liteDatabaseUrl(path = "."): string {
  return `sqlite:///${liteDatabasePath(path)}`;
}

export function liteSettings(
  path = ".",
  env: NodeJS.ProcessEnv = process.env,
): CodeWikiSettings {
  const directory = liteDir(path);
  mkdirSync(directory, { recursive: true });
  return getSettings({
    ...env,
    CODEWIKI_DATABASE_URL: liteDatabaseUrl(path),
    CODEWIKI_STORAGE_DIR: join(directory, "storage"),
  });
}

export function initLiteRepo(options: LiteRepoOptions = {}): LiteRepoContext {
  const root = liteRoot(options.path);
  mkdirSync(root, { recursive: true });
  const settings = liteSettings(root, options.env);
  const store = new CodeWikiStore(settings.databasePath);
  const scanner = new RepoScanner({ storageDir: settings.storageDir });
  const runtime = createBackendRuntime({ settings, store, scanner });
  const repo = store.upsertRepo(
    scanner.describe(root, {
      name: options.name,
      source_type: options.source_type ?? "local",
    }),
  );
  return {
    settings,
    store,
    scanner,
    services: runtime.services,
    repo,
    databasePath: settings.databasePath,
    liteDir: liteDir(root),
  };
}

export async function createLiteMcpServer(
  options: LiteRepoOptions & { sync?: boolean } = {},
): Promise<CodeWikiMCPServer> {
  const context = initLiteRepo(options);
  try {
    if (options.sync ?? true) {
      await syncLiteRepo(context);
    }
  } finally {
    context.store.close();
  }
  return new CodeWikiMCPServer({ settings: context.settings });
}

export function uninitLiteRepo(path = "."): boolean {
  const directory = liteDir(path);
  if (!existsSync(directory)) {
    return false;
  }
  rmSync(directory, { recursive: true, force: true });
  return true;
}

export function syncLiteRepo(
  context: LiteRepoContext,
): ReturnType<BackendServices["analysis"]["analyze"]> {
  return context.services.analysis.analyze(context.repo.id);
}

function expandHome(path: string): string {
  if (path === "~") {
    return process.env.HOME ?? path;
  }
  if (path.startsWith("~/")) {
    return join(process.env.HOME ?? "~", path.slice(2));
  }
  return path;
}
