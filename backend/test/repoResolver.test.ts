import { mkdirSync, mkdtempSync, realpathSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { CodeWikiStore } from "../src/db/store.js";
import { RepoScanner } from "../src/scanner/scanner.js";
import {
  ensureRepo,
  firstRepo,
  resolveRegisteredRepo,
  resolveRepo,
  selectedRepo,
} from "../src/services/repoResolver.js";
import type { RepoDescriptor } from "../src/types.js";

describe("repoResolver", () => {
  let store: CodeWikiStore | null = null;

  afterEach(() => {
    store?.close();
    store = null;
  });

  it("resolves registered repositories by id, name, prefix, path, and git URL", async () => {
    store = new CodeWikiStore(":memory:");
    const root = mkdtempSync(join(tmpdir(), "codewiki-repo-resolver-"));
    const repoPath = join(root, "alpha");
    mkdirSync(repoPath);

    const repo = store.upsertRepo(
      repoDescriptor({
        id: "alpha1234567890",
        name: "alpha",
        path: repoPath,
        git_url: "https://example.com/alpha.git",
      }),
    );

    expect((await resolveRegisteredRepo(store, repo.id)).id).toBe(repo.id);
    expect((await resolveRegisteredRepo(store, "alpha")).id).toBe(repo.id);
    expect((await resolveRegisteredRepo(store, "alpha123")).id).toBe(repo.id);
    expect((await resolveRegisteredRepo(store, repoPath)).id).toBe(repo.id);
    expect(
      (await resolveRegisteredRepo(store, "https://example.com/alpha.git")).id,
    ).toBe(repo.id);
    expect((await selectedRepo(store, undefined)).id).toBe(repo.id);
    expect((await firstRepo(store)).id).toBe(repo.id);
  });

  it("reports ambiguous names and prefixes", async () => {
    store = new CodeWikiStore(":memory:");
    store.upsertRepo(
      repoDescriptor({
        id: "shared-prefix-one",
        name: "same",
        path: "/tmp/one",
      }),
    );
    store.upsertRepo(
      repoDescriptor({
        id: "shared-prefix-two",
        name: "same",
        path: "/tmp/two",
      }),
    );

    await expect(resolveRegisteredRepo(store!, "same")).rejects.toThrow(
      "Repository name is ambiguous",
    );
    await expect(
      resolveRegisteredRepo(store!, "shared-prefix"),
    ).rejects.toThrow("Repository id prefix is ambiguous");
  });

  it("creates repositories from paths only when requested", async () => {
    store = new CodeWikiStore(":memory:");
    const root = mkdtempSync(join(tmpdir(), "codewiki-repo-resolver-create-"));
    const repoPath = join(root, "created");
    mkdirSync(repoPath);
    const scanner = new RepoScanner();

    await expect(
      resolveRepo(store!, scanner, repoPath, { createIfMissing: false }),
    ).rejects.toThrow("Repository not found");
    expect(store.listRepos()).toEqual([]);

    const created = await resolveRepo(store, scanner, repoPath);
    expect(created.path).toBe(repoPath);
    expect(store.getRepo(created.id)?.path).toBe(repoPath);

    const ensured = await ensureRepo(store, scanner, repoPath);
    expect(ensured.id).toBe(created.id);
  });

  it("matches registered repositories by real path", async () => {
    store = new CodeWikiStore(":memory:");
    const root = mkdtempSync(
      join(tmpdir(), "codewiki-repo-resolver-realpath-"),
    );
    const repoPath = join(root, "linked");
    mkdirSync(repoPath);
    const realRepoPath = realpathSync(repoPath);

    const repo = store.upsertRepo(
      repoDescriptor({
        id: "realpath123456789",
        name: "realpath-repo",
        path: repoPath,
      }),
    );

    expect((await resolveRegisteredRepo(store, realRepoPath)).id).toBe(repo.id);
  });
});

function repoDescriptor(overrides: Partial<RepoDescriptor>): RepoDescriptor {
  return {
    id: "repo-id",
    name: "repo",
    path: "/tmp/repo",
    source_type: "local",
    git_url: null,
    commit_hash: null,
    ...overrides,
  };
}
