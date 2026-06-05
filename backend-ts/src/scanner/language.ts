import { basename, extname } from "node:path";

const SOURCE_LANGUAGES = new Set([
  "python",
  "typescript",
  "javascript",
  "tsx",
  "jsx",
  "java",
  "go",
  "rust",
  "c",
  "cpp",
  "csharp",
  "kotlin",
  "ruby",
  "php",
  "swift",
]);

const EXTENSION_LANGUAGE: Record<string, string> = {
  ".py": "python",
  ".pyi": "python",
  ".js": "javascript",
  ".mjs": "javascript",
  ".cjs": "javascript",
  ".jsx": "jsx",
  ".ts": "typescript",
  ".mts": "typescript",
  ".cts": "typescript",
  ".tsx": "tsx",
  ".java": "java",
  ".go": "go",
  ".rs": "rust",
  ".c": "c",
  ".h": "c",
  ".cc": "cpp",
  ".cpp": "cpp",
  ".cxx": "cpp",
  ".hpp": "cpp",
  ".cs": "csharp",
  ".kt": "kotlin",
  ".kts": "kotlin",
  ".rb": "ruby",
  ".php": "php",
  ".swift": "swift",
  ".md": "markdown",
  ".mdx": "mdx",
  ".json": "json",
  ".jsonc": "jsonc",
  ".yaml": "yaml",
  ".yml": "yaml",
  ".toml": "toml",
  ".ini": "ini",
  ".env": "dotenv",
  ".sh": "shell",
  ".bash": "shell",
  ".zsh": "shell",
  ".sql": "sql",
  ".html": "html",
  ".css": "css",
  ".scss": "scss",
};

const FILENAME_LANGUAGE: Record<string, string> = {
  Dockerfile: "dockerfile",
  Containerfile: "dockerfile",
  Makefile: "makefile",
  Rakefile: "ruby",
  Gemfile: "ruby",
  "go.mod": "go-mod",
  "go.sum": "go-sum",
  "package.json": "json",
  "tsconfig.json": "jsonc",
  "pyproject.toml": "toml",
  "requirements.txt": "requirements",
};

export function detectLanguage(path: string): string {
  const name = basename(path);
  if (FILENAME_LANGUAGE[name]) {
    return FILENAME_LANGUAGE[name];
  }
  if (name.startsWith(".env")) {
    return "dotenv";
  }
  return EXTENSION_LANGUAGE[extname(path)] ?? "unknown";
}

export function isSourceLanguage(language: string): boolean {
  return SOURCE_LANGUAGES.has(language);
}
