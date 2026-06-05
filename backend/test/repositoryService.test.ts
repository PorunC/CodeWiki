import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { CodeWikiStore } from "../src/db/store.js";
import { CodeWikiError } from "../src/errors.js";
import { RepoScanner } from "../src/scanner/scanner.js";
import { RepositoryService } from "../src/services/repositoryService.js";

describe("RepositoryService", () => {
  let store: CodeWikiStore | null = null;

  afterEach(() => {
    store?.close();
    store = null;
  });

  it("registers, scans, resolves, lists, reads files, and deletes repositories", () => {
    const root = mkdtempSync(join(tmpdir(), "codewiki-repository-service-"));
    const repoPath = join(root, "repo");
    mkdirSync(join(repoPath, "src"), { recursive: true });
    writeFileSync(join(repoPath, "README.md"), "# Service Repo\n");
    writeFileSync(
      join(repoPath, "src", "main.ts"),
      "export function run() { return 42; }\n",
    );

    store = new CodeWikiStore(":memory:");
    const service = new RepositoryService(store, new RepoScanner());

    const registered = service.register(repoPath, { name: "service-repo" });
    expect(registered).toMatchObject({
      name: "service-repo",
      path: repoPath,
      source_type: "local",
    });
    expect(service.list().map((repo) => repo.id)).toEqual([registered.id]);
    expect(service.resolveRegistered("service-repo").id).toBe(registered.id);

    const scan = service.scan(repoPath, { name: "scan-repo" });
    expect(scan.repo.name).toBe("scan-repo");
    expect(scan.files.map((file) => file.path)).toEqual([
      "README.md",
      "src/main.ts",
    ]);

    const files = service.filesForId(registered.id);
    expect(files.repo.id).toBe(registered.id);
    expect(files.scan.files.map((file) => file.path)).toEqual([
      "README.md",
      "src/main.ts",
    ]);

    const deleted = service.deleteBySelector("service-repo");
    expect(deleted).toMatchObject({
      repo: { id: registered.id },
      deleted: true,
    });
    expect(service.list()).toEqual([]);
    expect(() => service.get(registered.id)).toThrow(CodeWikiError);
  });
});
