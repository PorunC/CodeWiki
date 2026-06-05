import { existsSync, realpathSync, statSync } from "node:fs";
import { resolve } from "node:path";
import type { CodeWikiStoreApi } from "../db/types.js";
import { conflictError, notFoundError, validationError } from "../errors.js";
import type { RepoScanner } from "../scanner/scanner.js";
import type { RepoDescriptor } from "../types.js";

export type RepoResolveOptions = {
  createIfMissing?: boolean;
  defaultSelector?: string;
};

export async function resolveRegisteredRepo(
  store: CodeWikiStoreApi,
  selector: string,
): Promise<RepoDescriptor> {
  const selected = normalizeSelector(selector);
  const match = await findRegisteredRepo(store, selected);
  if (match) {
    return match;
  }
  throw notFoundError("Repository", selected);
}

export async function firstRepo(
  store: CodeWikiStoreApi,
): Promise<RepoDescriptor> {
  const repo = (await store.listRepos())[0];
  if (!repo) {
    throw notFoundError("Repository", "first");
  }
  return repo;
}

export async function selectedRepo(
  store: CodeWikiStoreApi,
  selector: string | undefined,
): Promise<RepoDescriptor> {
  return selector ? resolveRegisteredRepo(store, selector) : firstRepo(store);
}

export async function ensureRepo(
  store: CodeWikiStoreApi,
  scanner: RepoScanner,
  selector: string,
): Promise<RepoDescriptor> {
  try {
    return await resolveRegisteredRepo(store, selector);
  } catch {
    return store.upsertRepo(scanner.describe(selector));
  }
}

export async function resolveRepo(
  store: CodeWikiStoreApi,
  scanner: RepoScanner,
  selector: string | null | undefined,
  options: RepoResolveOptions = {},
): Promise<RepoDescriptor> {
  const selected = normalizeSelector(
    selector ?? options.defaultSelector ?? ".",
  );
  const match = await findRegisteredRepo(store, selected);
  if (match) {
    return match;
  }
  if (options.createIfMissing === false) {
    throw notFoundError("Repository", selected);
  }
  return store.upsertRepo(scanner.describe(selected));
}

export function looksLikeExistingDirectory(value: string): boolean {
  try {
    const path = resolve(value);
    return existsSync(path) && statSync(path).isDirectory();
  } catch {
    return false;
  }
}

async function findRegisteredRepo(
  store: CodeWikiStoreApi,
  selector: string,
): Promise<RepoDescriptor | null> {
  const exact = await store.getRepo(selector);
  if (exact) {
    return exact;
  }

  const repos = await store.listRepos();
  const resolvedSelectorPath = resolvedExistingDirectory(selector);
  const pathMatches = repos.filter(
    (repo) =>
      repo.path === selector ||
      repo.git_url === selector ||
      (resolvedSelectorPath !== null &&
        resolvedExistingDirectory(repo.path) === resolvedSelectorPath),
  );
  if (pathMatches.length === 1) {
    return pathMatches[0]!;
  }
  if (pathMatches.length > 1) {
    throw conflictError(`Repository path is ambiguous: ${selector}`, {
      selector,
    });
  }

  const nameMatches = repos.filter((repo) => repo.name === selector);
  if (nameMatches.length === 1) {
    return nameMatches[0]!;
  }
  if (nameMatches.length > 1) {
    throw conflictError(`Repository name is ambiguous: ${selector}`, {
      selector,
    });
  }

  const prefixMatches = repos.filter((repo) => repo.id.startsWith(selector));
  if (prefixMatches.length === 1) {
    return prefixMatches[0]!;
  }
  if (prefixMatches.length > 1) {
    throw conflictError(`Repository id prefix is ambiguous: ${selector}`, {
      selector,
    });
  }

  return null;
}

function resolvedExistingDirectory(value: string): string | null {
  try {
    const path = resolve(value);
    return existsSync(path) && statSync(path).isDirectory()
      ? realpathSync(path)
      : null;
  } catch {
    return null;
  }
}

function normalizeSelector(selector: string): string {
  const selected = selector.trim();
  if (!selected) {
    throw validationError("Repository selector must be a non-empty string.");
  }
  return selected;
}
