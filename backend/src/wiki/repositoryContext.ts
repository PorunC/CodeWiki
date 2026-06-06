import {
  readdirSync,
  readFileSync,
  statSync,
  type Dirent,
  type Stats,
} from "node:fs";
import { basename, relative, resolve } from "node:path";
import type { JsonObject } from "../types.js";

const MAX_REPOSITORY_TREE_DEPTH = 3;
const MAX_REPOSITORY_TREE_ENTRIES_PER_DIR = 80;
const MAX_README_CHARS = 6000;

const README_NAMES = [
  "README.md",
  "README.MD",
  "readme.md",
  "README.rst",
  "README.txt",
  "README",
];

const COMMON_KEY_FILES = [
  "README.md",
  "pyproject.toml",
  "package.json",
  "tsconfig.json",
  "vite.config.ts",
  "next.config.ts",
  "requirements.txt",
  "Dockerfile",
  "docker-compose.yml",
  "compose.yaml",
  "Makefile",
  ".env.example",
];

const EXCLUDED_CONTEXT_DIRS = new Set([
  ".git",
  ".hg",
  ".svn",
  ".idea",
  ".vscode",
  "__pycache__",
  ".pytest_cache",
  ".ruff_cache",
  ".mypy_cache",
  ".venv",
  "venv",
  "node_modules",
  "dist",
  "build",
  "coverage",
  ".next",
  ".nuxt",
  ".turbo",
  "target",
  "out",
  ".output",
]);

export function repositoryFilesystemContext(repoPath: string): JsonObject {
  const root = resolve(repoPath);
  return {
    project_type: detectProjectType(root),
    directory_tree_format: "compact",
    directory_tree: directoryTree(root),
    readme_content: readmeContent(root),
    key_files: keyFiles(root),
    entry_points: entryPoints(root),
  };
}

function directoryTree(root: string): string {
  if (!safeStat(root)?.isDirectory()) {
    return basename(root);
  }
  const lines = [basename(root)];
  appendTree(root, lines, 0);
  return lines.join("\n");
}

function appendTree(directory: string, lines: string[], depth: number): void {
  if (depth >= MAX_REPOSITORY_TREE_DEPTH) {
    return;
  }
  const entries = safeReadDir(directory)
    .filter(
      (entry) =>
        !entry.name.startsWith(".") && !EXCLUDED_CONTEXT_DIRS.has(entry.name),
    )
    .sort((left, right) => {
      const leftIsFile = left.isFile();
      const rightIsFile = right.isFile();
      return (
        Number(leftIsFile) - Number(rightIsFile) ||
        left.name.toLowerCase().localeCompare(right.name.toLowerCase())
      );
    })
    .slice(0, MAX_REPOSITORY_TREE_ENTRIES_PER_DIR);
  for (const entry of entries) {
    const absolutePath = resolve(directory, entry.name);
    const suffix = entry.isDirectory() ? "/" : "";
    lines.push(`${"  ".repeat(depth + 1)}- ${entry.name}${suffix}`);
    if (entry.isDirectory()) {
      appendTree(absolutePath, lines, depth + 1);
    }
  }
}

function readmeContent(root: string): string {
  for (const name of README_NAMES) {
    const path = resolve(root, name);
    if (!safeStat(path)?.isFile()) {
      continue;
    }
    const content = safeReadFile(path).trim();
    return content.length > MAX_README_CHARS
      ? `${content.slice(0, MAX_README_CHARS).trimEnd()}\n\n[README truncated]`
      : content;
  }
  return "";
}

function keyFiles(root: string): string[] {
  const paths = COMMON_KEY_FILES.filter((name) =>
    safeStat(resolve(root, name))?.isFile(),
  );
  paths.push(
    ...safeReadDir(root)
      .filter(
        (entry) =>
          entry.isFile() &&
          (entry.name.endsWith(".sln") || entry.name.endsWith(".csproj")),
      )
      .map((entry) => entry.name),
  );
  return uniqueStrings(paths).sort((left, right) => left.localeCompare(right));
}

function entryPoints(root: string): string[] {
  const directPatterns = [
    "backend/app/main.py",
    "app.py",
    "main.py",
    "__main__.py",
    "manage.py",
    "frontend/src/main.tsx",
    "frontend/src/main.ts",
    "src/main.tsx",
    "src/main.ts",
    "src/App.tsx",
    "src/App.vue",
    "Program.cs",
    "Startup.cs",
  ].filter((filePath) => safeStat(resolve(root, filePath))?.isFile());
  const goCommandEntries = safeReadDir(resolve(root, "cmd")).flatMap(
    (entry) => {
      if (!entry.isDirectory()) {
        return [];
      }
      const filePath = `cmd/${entry.name}/main.go`;
      return safeStat(resolve(root, filePath))?.isFile() ? [filePath] : [];
    },
  );
  return uniqueStrings([...directPatterns, ...goCommandEntries])
    .sort((left, right) => left.localeCompare(right))
    .slice(0, 12);
}

function detectProjectType(root: string): string {
  const types: string[] = [];
  if (
    safeStat(resolve(root, "pyproject.toml"))?.isFile() ||
    safeStat(resolve(root, "requirements.txt"))?.isFile()
  ) {
    types.push("python");
  }
  const packageTexts = packageJsonFiles(root)
    .slice(0, 5)
    .map((filePath) => safeReadFile(resolve(root, filePath)))
    .filter(Boolean);
  if (packageTexts.length) {
    const packageText = packageTexts.join("\n");
    types.push(
      /"(react|next|vite|vue|angular)"/.test(packageText)
        ? "frontend"
        : "nodejs",
    );
  }
  if (
    safeReadDir(root).some(
      (entry) => entry.name.endsWith(".sln") || entry.name.endsWith(".csproj"),
    )
  ) {
    types.push("dotnet");
  }
  if (safeStat(resolve(root, "go.mod"))?.isFile()) {
    types.push("go");
  }
  if (safeStat(resolve(root, "Cargo.toml"))?.isFile()) {
    types.push("rust");
  }
  if (
    safeStat(resolve(root, "pom.xml"))?.isFile() ||
    safeReadDir(root).some((entry) => entry.name.startsWith("build.gradle"))
  ) {
    types.push("java");
  }
  if (!types.length) {
    return "unknown";
  }
  return types.length > 1
    ? `fullstack:${types.join("+")}`
    : (types[0] ?? "unknown");
}

function safeReadDir(path: string): Dirent[] {
  try {
    return readdirSync(path, { withFileTypes: true });
  } catch {
    return [];
  }
}

function safeReadFile(path: string): string {
  try {
    return readFileSync(path, "utf8");
  } catch {
    return "";
  }
}

function safeStat(path: string): Stats | null {
  try {
    return statSync(path);
  } catch {
    return null;
  }
}

function packageJsonFiles(root: string): string[] {
  const results: string[] = [];
  const visit = (directory: string, depth: number) => {
    if (results.length >= 5 || depth > MAX_REPOSITORY_TREE_DEPTH + 2) {
      return;
    }
    for (const entry of safeReadDir(directory)) {
      if (entry.name.startsWith(".") || EXCLUDED_CONTEXT_DIRS.has(entry.name)) {
        continue;
      }
      const absolutePath = resolve(directory, entry.name);
      const relativePath = relative(root, absolutePath).replace(/\\/g, "/");
      if (entry.isFile() && entry.name === "package.json") {
        results.push(relativePath);
      } else if (entry.isDirectory()) {
        visit(absolutePath, depth + 1);
      }
      if (results.length >= 5) {
        return;
      }
    }
  };
  visit(root, 0);
  return results;
}

function uniqueStrings(values: string[]): string[] {
  return [...new Set(values.map((value) => value.trim()).filter(Boolean))];
}
