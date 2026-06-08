import { existsSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";
import ignore from "ignore";

const DEFAULT_IGNORE_PATTERNS = [
  ".git/",
  ".codewiki/",
  ".hg/",
  ".svn/",
  ".idea/",
  ".vscode/",
  ".env",
  ".env.*",
  "__pycache__/",
  ".pytest_cache/",
  ".ruff_cache/",
  ".mypy_cache/",
  ".venv/",
  "venv/",
  "node_modules/",
  "dist/",
  "build/",
  "coverage/",
  ".next/",
  ".nuxt/",
  ".turbo/",
  "target/",
  "*.pyc",
  "*.pyo",
  "*.so",
  "*.dylib",
  "*.dll",
  "*.exe",
  "*.class",
  "*.jar",
  "*.zip",
  "*.tar",
  "*.gz",
  "*.png",
  "*.jpg",
  "*.jpeg",
  "*.gif",
  "*.webp",
  "*.ico",
  "*.pdf",
  "uv.lock",
  "package-lock.json",
  "pnpm-lock.yaml",
  "yarn.lock",
];

export class IgnoreStack {
  private readonly matchers: Array<{
    base: string;
    matcher: ReturnType<typeof ignore>;
  }> = [];

  constructor(private readonly root: string) {
    this.matchers.push({
      base: root,
      matcher: ignore().add(DEFAULT_IGNORE_PATTERNS),
    });
  }

  addGitignore(directory: string): void {
    const gitignorePath = join(directory, ".gitignore");
    if (!existsSync(gitignorePath)) {
      return;
    }
    const lines = readFileSync(gitignorePath, "utf8")
      .split(/\r?\n/)
      .filter((line) => line.trim() && !line.trim().startsWith("#"));
    if (lines.length) {
      this.matchers.push({ base: directory, matcher: ignore().add(lines) });
    }
  }

  ignores(relativePathFromRoot: string, isDirectory: boolean): boolean {
    const normalizedPath = normalizeIgnorePath(relativePathFromRoot);
    let ignored = false;
    for (const { base, matcher } of this.matchers) {
      const baseRelative = normalizeIgnorePath(relative(this.root, base));
      if (
        baseRelative &&
        normalizedPath !== baseRelative &&
        !normalizedPath.startsWith(`${baseRelative}/`)
      ) {
        continue;
      }
      const candidate = baseRelative
        ? normalizeIgnorePath(normalizedPath.slice(baseRelative.length + 1))
        : normalizedPath;
      if (!candidate || candidate.startsWith("../")) {
        continue;
      }
      ignored =
        matcher.ignores(isDirectory ? `${candidate}/` : candidate) ||
        matcher.ignores(candidate);
    }
    return ignored;
  }
}

function normalizeIgnorePath(value: string): string {
  return value
    .split("\\")
    .join("/")
    .replace(/^\/+/, "")
    .replace(/^\.\//, "")
    .replace(/\/+/g, "/");
}
