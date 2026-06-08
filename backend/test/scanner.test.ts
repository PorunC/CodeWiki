import { mkdtempSync, writeFileSync, mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { IgnoreStack } from "../src/scanner/ignore.js";
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

  it("normalizes Windows-style ignore candidates and scopes nested gitignore files", () => {
    const repo = mkdtempSync(join(tmpdir(), "codewiki-scan-ignore-"));
    mkdirSync(join(repo, "src"), { recursive: true });
    mkdirSync(join(repo, "tasks"), { recursive: true });
    writeFileSync(join(repo, "src", ".gitignore"), "tasks/\n");
    writeFileSync(join(repo, "src", "main.ts"), "export const main = 1;\n");
    writeFileSync(join(repo, "tasks", "task.ts"), "export const task = 1;\n");

    const matcher = new IgnoreStack(repo);
    matcher.addGitignore(join(repo, "src"));

    expect(() => matcher.ignores("/tasks", true)).not.toThrow();
    expect(matcher.ignores("/tasks", true)).toBe(false);
    expect(matcher.ignores("src/tasks", true)).toBe(true);

    const scan = new RepoScanner().scan(repo);
    expect(scan.files.map((file) => file.path)).toEqual([
      "src/.gitignore",
      "src/main.ts",
      "tasks/task.ts",
    ]);
  });
});
