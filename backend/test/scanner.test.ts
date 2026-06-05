import { mkdtempSync, writeFileSync, mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { RepoScanner } from "../src/scanner/scanner.js";

describe("RepoScanner", () => {
  it("scans files, respects gitignore, and detects source languages", () => {
    const repo = mkdtempSync(join(tmpdir(), "codewiki-scan-"));
    writeFileSync(
      join(repo, ".gitignore"),
      "ignored.py\nnode_modules/\n*.log\n!keep.log\n",
    );
    writeFileSync(join(repo, "main.py"), "def run():\n    return 42\n");
    writeFileSync(join(repo, "ignored.py"), "print('ignored')\n");
    writeFileSync(join(repo, "keep.log"), "keep\n");
    writeFileSync(join(repo, "skip.log"), "skip\n");
    mkdirSync(join(repo, "node_modules"));
    writeFileSync(join(repo, "node_modules", "package.js"), "ignored()\n");

    const scan = new RepoScanner().scan(repo);
    const paths = new Set(scan.files.map((file) => file.path));

    expect(paths.has("main.py")).toBe(true);
    expect(paths.has("keep.log")).toBe(true);
    expect(paths.has("ignored.py")).toBe(false);
    expect(paths.has("skip.log")).toBe(false);
    expect(paths.has("node_modules/package.js")).toBe(false);
    expect(scan.files.find((file) => file.path === "main.py")?.language).toBe(
      "python",
    );
    expect(scan.files.find((file) => file.path === "main.py")?.is_source).toBe(
      true,
    );
  });
});
