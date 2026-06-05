import { existsSync, realpathSync, statSync } from "node:fs";
import { resolve } from "node:path";
import type { CodeWikiStore } from "../db/store.js";
import { conflictError, notFoundError, validationError } from "../errors.js";
import type { RepoScanner } from "../scanner/scanner.js";
import type { RepoDescriptor } from "../types.js";

export type RepoResolveOptions = {
  createIfMissing?: boolean;
  defaultSelector?: string;
};

export function resolveRegisteredRepo(
  store: CodeWikiStore,
  selector: string,
): RepoDescriptor {
  const selected = normalizeSelector(selector);
  const match = findRegisteredRepo(store, selected);
  if (match) {
    return match;
  }
  throw notFoundError("Repository", selected);
}

export function firstRepo(store: CodeWikiStore): RepoDescriptor {
  const repo = store.listRepos()[0];
  if (!repo) {
    throw notFoundError("Repository", "first");
  }
  return repo;
}

export function selectedRepo(
  store: CodeWikiStore,
  selector: string | undefined,
): RepoDescriptor {
  return selector ? resolveRegisteredRepo(store, selector) : firstRepo(store);
}

export function ensureRepo(
  store: CodeWikiStore,
  scanner: RepoScanner,
  selector: string,
): RepoDescriptor {
  try {
    return resolveRegisteredRepo(store, selector);
  } catch {
    return store.upsertRepo(scanner.describe(selector));
  }
}

export function resolveRepo(
  store: CodeWikiStore,
  scanner: RepoScanner,
  selector: string | null | undefined,
  options: RepoResolveOptions = {},
): RepoDescriptor {
  const selected = normalizeSelector(
    selector ?? options.defaultSelector ?? ".",
  );
  const match = findRegisteredRepo(store, selected);
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

function findRegisteredRepo(
  store: CodeWikiStore,
  selector: string,
): RepoDescriptor | null {
  const exact = store.getRepo(selector);
  if (exact) {
    return exact;
  }

  const repos = store.listRepos();
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
