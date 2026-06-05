import { spawnSync } from "node:child_process";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const packageRoot = join(import.meta.dirname, "..");
const tsxLoader = join(
  packageRoot,
  "node_modules",
  "tsx",
  "dist",
  "loader.mjs",
);
const cliEntry = join(packageRoot, "src", "cli.ts");

describe("codewiki CLI", () => {
  it("updates env files and reads them as default runtime configuration", () => {
    const root = mkdtempSync(join(tmpdir(), "codewiki-cli-config-"));
    const envFile = join(root, ".env");
    const databaseUrl = `sqlite:///${join(root, "configured.sqlite3")}`;
    const env = withoutCodeWikiEnv(process.env);

    const updated = runJson<{
      created: boolean;
      env_file: string;
      updated: Record<string, string>;
    }>(
      [
        "config",
        "--config-file",
        envFile,
        "--set",
        "CODEWIKI_APP_NAME=Configured Wiki",
        "--database-url",
        databaseUrl,
        "--profile",
        "page",
        "--model",
        "openai/page",
        "--api-key",
        "top-secret",
        "--json",
      ],
      env,
      { cwd: root },
    );

    expect(updated.created).toBe(true);
    expect(updated.env_file).toBe(envFile);
    expect(updated.updated).toMatchObject({
      CODEWIKI_APP_NAME: "Configured Wiki",
      CODEWIKI_DATABASE_URL: databaseUrl,
      CODEWIKI_LLM__PROFILES__PAGE__API_KEY: "********",
      CODEWIKI_LLM__PROFILES__PAGE__MODEL: "openai/page",
    });
    expect(readFileSync(envFile, "utf8")).toContain(
      'CODEWIKI_APP_NAME="Configured Wiki"',
    );

    const masked = runJson<{ values: Record<string, string> }>(
      [
        "config",
        "--config-file",
        envFile,
        "--get",
        "CODEWIKI_LLM__PROFILES__PAGE__API_KEY",
        "--json",
      ],
      env,
      { cwd: root },
    );
    expect(masked.values.CODEWIKI_LLM__PROFILES__PAGE__API_KEY).toBe(
      "********",
    );

    const unmasked = runJson<{ values: Record<string, string> }>(
      [
        "config",
        "--config-file",
        envFile,
        "--get",
        "CODEWIKI_LLM__PROFILES__PAGE__API_KEY",
        "--show-secrets",
        "--json",
      ],
      env,
      { cwd: root },
    );
    expect(unmasked.values.CODEWIKI_LLM__PROFILES__PAGE__API_KEY).toBe(
      "top-secret",
    );

    const runtime = runJson<{
      app_name: string;
      database_url: string;
      llm: {
        profiles: Record<string, { has_api_key: boolean; model: string }>;
      };
    }>(["config", "--json"], env, { cwd: root });

    expect(runtime.app_name).toBe("Configured Wiki");
    expect(runtime.database_url).toBe(databaseUrl);
    expect(runtime.llm.profiles.page).toMatchObject({
      has_api_key: true,
      model: "openai/page",
    });
  }, 30_000);

  it("runs wiki update, page regeneration, and translation commands", () => {
    const root = mkdtempSync(join(tmpdir(), "codewiki-cli-"));
    const repo = join(root, "repo");
    mkdirSync(join(repo, "src"), { recursive: true });
    writeFileSync(join(repo, "README.md"), "# CLI Repo\n");
    writeFileSync(
      join(repo, "src", "main.ts"),
      [
        "import { helper } from './util';",
        "export function run() {",
        "  return helper(41);",
        "}",
        "",
      ].join("\n"),
    );
    writeFileSync(
      join(repo, "src", "util.ts"),
      "export function helper(x: number) { return x + 1; }\n",
    );

    const env = {
      ...process.env,
      CODEWIKI_DATABASE_URL: `sqlite:///${join(root, "codewiki.sqlite3")}`,
      CODEWIKI_STORAGE_DIR: join(root, "storage"),
    };

    const added = runJson<{ id: string; name: string }>(
      ["repos", "add", repo, "--name", "cli-repo", "--json"],
      env,
    );
    expect(added.name).toBe("cli-repo");

    const fileTree = runCli(
      ["files", "tree", "--repo", "cli-repo"],
      env,
    ).stdout;
    expect(fileTree.trim().startsWith("{")).toBe(false);
    expect(fileTree).toContain("cli-repo/");
    expect(fileTree).toContain("  src/");
    expect(fileTree).toContain("    main.ts");
    expect(fileTree).toContain("  README.md");

    const fileList = runJson<{
      files: Array<{ path: string; is_source: boolean }>;
    }>(["files", "list", "--repo", "cli-repo", "--source-only", "--json"], env);
    expect(fileList.files.map((file) => file.path)).toEqual([
      "src/main.ts",
      "src/util.ts",
    ]);
    expect(fileList.files.every((file) => file.is_source)).toBe(true);

    const analyzedCurrentDir = runJson<{
      status: string;
      repo_id: string;
      node_count: number;
    }>(["analyze", "--json"], env, { cwd: repo });
    expect(analyzedCurrentDir.status).toBe("done");
    expect(analyzedCurrentDir.repo_id).toBe(added.id);
    expect(analyzedCurrentDir.node_count).toBeGreaterThanOrEqual(4);

    const reposAfterCurrentDirAnalyze = runJson<
      Array<{ id: string; name: string }>
    >(["repos", "list", "--json"], env);
    expect(
      reposAfterCurrentDirAnalyze.filter((repo) => repo.id === added.id),
    ).toEqual([expect.objectContaining({ name: "cli-repo" })]);

    const analyzed = runJson<{ status: string; node_count: number }>(
      [
        "analyze",
        added.id,
        "--force",
        "--progress",
        "--no-community-summaries",
        "--json",
      ],
      env,
    );
    expect(analyzed.status).toBe("done");
    expect(analyzed.node_count).toBeGreaterThanOrEqual(4);

    const catalog = runJson<{
      title: string;
      validation_errors: string[];
      structure: { items: Array<{ slug: string }> };
    }>(["wiki", "catalog", added.id, "--json"], env);
    expect(catalog.title).toBe("cli-repo Wiki");
    expect(catalog.validation_errors).toEqual([]);
    expect(catalog.structure.items.map((item) => item.slug)).toEqual([
      "root",
      "src",
    ]);

    const generated = runJson<{
      page_count: number;
      pages: Array<{ slug: string }>;
    }>(["wiki", "pages", added.id, "--json"], env);
    expect(generated.page_count).toBeGreaterThanOrEqual(1);
    const slug = generated.pages[0]?.slug;
    expect(slug).toBeTruthy();

    writeFileSync(
      join(repo, "src", "util.ts"),
      [
        "export function helper(x: number) { return x + 1; }",
        "export function double(x: number) { return x * 2; }",
        "",
      ].join("\n"),
    );
    const repositoryUpdate = runJson<{
      status: string;
      mode: string;
      plan: { changed_files: string[]; affected_files: string[] };
      wiki_regeneration: { status?: string; generated_pages?: string[] };
    }>(["update", added.id, "--json"], env);
    expect(repositoryUpdate.status).toBe("done");
    expect(repositoryUpdate.mode).toBe("typescript_update");
    expect(repositoryUpdate.plan.changed_files).toEqual(["src/util.ts"]);
    expect(repositoryUpdate.plan.affected_files).toEqual(["src/util.ts"]);
    expect(repositoryUpdate.wiki_regeneration.status).toBe("updated");
    expect(
      repositoryUpdate.wiki_regeneration.generated_pages?.length,
    ).toBeGreaterThanOrEqual(1);

    const updated = runJson<{ status: string; generated_pages: string[] }>(
      ["wiki", "update", added.id, "--json"],
      env,
    );
    expect(updated.status).toBe("updated");
    expect(updated.generated_pages.length).toBeGreaterThanOrEqual(1);

    const regenerated = runJson<{ slug: string; status: string }>(
      ["wiki", "page", slug!, added.id, "--json"],
      env,
    );
    expect(regenerated.slug).toBe(slug);
    expect(regenerated.status).toBe("generated");

    const translated = runJson<{ target_language: string; page_count: number }>(
      ["wiki", "translate", "zh", added.id, "--json"],
      env,
    );
    expect(translated.target_language).toBe("zh");
    expect(translated.page_count).toBeGreaterThanOrEqual(1);

    const translatedPage = runJson<{ language_code: string; slug: string }>(
      ["wiki", "read", slug!, added.id, "--language", "zh", "--json"],
      env,
    );
    expect(translatedPage.language_code).toBe("zh");
    expect(translatedPage.slug).toBe(slug);
  }, 30_000);

  it("starts MCP lite mode with a project-local database", () => {
    const root = mkdtempSync(join(tmpdir(), "codewiki-cli-lite-"));
    const repo = join(root, "repo");
    mkdirSync(join(repo, "src"), { recursive: true });
    writeFileSync(join(repo, "README.md"), "# Lite Repo\n");
    writeFileSync(
      join(repo, "src", "main.ts"),
      "export function run() { return 42; }\n",
    );

    const response = runCli(
      ["mcp", "--lite", "--path", repo, "--no-sync"],
      process.env,
      [
        {
          jsonrpc: "2.0",
          id: 1,
          method: "initialize",
          params: { protocolVersion: "2024-11-05" },
        },
        {
          jsonrpc: "2.0",
          id: 2,
          method: "tools/call",
          params: { name: "codewiki_repos_list", arguments: {} },
        },
        {
          jsonrpc: "2.0",
          id: 3,
          method: "tools/call",
          params: { name: "codewiki_analyze", arguments: {} },
        },
      ]
        .map((message) => JSON.stringify(message))
        .join("\n") + "\n",
    );
    const messages = response.stdout
      .trim()
      .split("\n")
      .filter(Boolean)
      .map((line) => JSON.parse(line) as Record<string, unknown>);
    expect(messages[0]).toMatchObject({
      result: { serverInfo: { name: "codewiki" } },
    });
    const repos = toolText<Array<{ name: string; path: string }>>(
      responseAt(messages, 1),
    );
    expect(repos).toEqual([
      expect.objectContaining({ name: "repo", path: repo }),
    ]);
    const analysis = toolText<{ status: string; node_count: number }>(
      responseAt(messages, 2),
    );
    expect(analysis.status).toBe("done");
    expect(analysis.node_count).toBeGreaterThanOrEqual(2);
    expect(existsSync(join(repo, ".codewiki", "codewiki-lite.sqlite3"))).toBe(
      true,
    );
  }, 30_000);

  it("runs Lite CLI index, query, context, files, affected, and uninit commands", () => {
    const root = mkdtempSync(join(tmpdir(), "codewiki-cli-lite-"));
    const repo = join(root, "repo");
    mkdirSync(join(repo, "src"), { recursive: true });
    writeFileSync(join(repo, "README.md"), "# Lite CLI Repo\n");
    writeFileSync(
      join(repo, "src", "main.ts"),
      [
        "import { helper } from './util';",
        "export function run() {",
        "  return helper(41);",
        "}",
        "",
      ].join("\n"),
    );
    writeFileSync(
      join(repo, "src", "util.ts"),
      "export function helper(x: number) { return x + 1; }\n",
    );

    const indexed = runJson<{
      status: string;
      node_count: number;
      database_path: string;
    }>(["lite", "index", repo, "--json"], process.env);
    expect(indexed.status).toBe("done");
    expect(indexed.node_count).toBeGreaterThanOrEqual(4);
    expect(indexed.database_path).toBe(
      join(repo, ".codewiki", "codewiki-lite.sqlite3"),
    );
    expect(existsSync(indexed.database_path)).toBe(true);

    const status = runJson<{
      node_count: number;
      file_count: number;
      pending_sync: boolean;
    }>(["lite", "status", repo, "--json"], process.env);
    expect(status.node_count).toBe(indexed.node_count);
    expect(status.file_count).toBeGreaterThanOrEqual(3);
    expect(status.pending_sync).toBe(false);

    const query = runJson<{
      results: Array<{ node: { name: string; file_path: string } }>;
    }>(["lite", "query", "helper", repo, "--json"], process.env);
    expect(
      query.results.some(
        (hit) =>
          hit.node.name === "helper" && hit.node.file_path === "src/util.ts",
      ),
    ).toBe(true);

    const node = runJson<{
      node: { name: string };
      source_sections: Array<{ content?: string }>;
    }>(["lite", "node", "helper", repo, "--json"], process.env);
    expect(node.node.name).toBe("helper");
    expect(
      node.source_sections.some((section) =>
        section.content?.includes("helper"),
      ),
    ).toBe(true);

    const files = runJson<{
      source: string;
      files: Array<{ path: string; is_source: boolean }>;
    }>(["lite", "files", repo, "--source-only", "--json"], process.env);
    expect(files.source).toBe("index");
    expect(files.files.map((file) => file.path)).toEqual([
      "src/main.ts",
      "src/util.ts",
    ]);
    expect(files.files.every((file) => file.is_source)).toBe(true);

    const affected = runJson<{
      affected_files: string[];
      affected_node_ids: string[];
    }>(
      ["lite", "affected", "src/util.ts", "--path", repo, "--json"],
      process.env,
    );
    expect(affected.affected_files).toContain("src/util.ts");
    expect(affected.affected_node_ids.length).toBeGreaterThanOrEqual(1);

    const removed = runJson<{ deleted: boolean; database_path: string }>(
      ["lite", "uninit", repo, "--force", "--json"],
      process.env,
    );
    expect(removed.deleted).toBe(true);
    expect(removed.database_path).toBe(
      join(repo, ".codewiki", "codewiki-lite.sqlite3"),
    );
    expect(existsSync(removed.database_path)).toBe(false);
  }, 30_000);
});

function runJson<T>(
  args: string[],
  env: NodeJS.ProcessEnv,
  options: RunCliOptions = {},
): T {
  return JSON.parse(runCli([...args], env, options).stdout) as T;
}

type RunCliOptions = {
  cwd?: string;
  input?: string;
};

function runCli(
  args: string[],
  env: NodeJS.ProcessEnv,
  optionsOrInput: RunCliOptions | string = {},
): { stdout: string; stderr: string } {
  const options =
    typeof optionsOrInput === "string"
      ? { input: optionsOrInput }
      : optionsOrInput;
  const result = spawnSync(
    process.execPath,
    ["--import", tsxLoader, cliEntry, ...args],
    {
      cwd: options.cwd ?? packageRoot,
      env,
      input: options.input,
      encoding: "utf8",
    },
  );
  if (result.status !== 0) {
    throw new Error(
      [
        `CLI command failed: codewiki ${args.join(" ")}`,
        result.stdout.trim(),
        result.stderr.trim(),
      ]
        .filter(Boolean)
        .join("\n"),
    );
  }
  return { stdout: result.stdout, stderr: result.stderr };
}

function toolText<T>(message: Record<string, unknown>): T {
  const result = message.result as {
    content: Array<{ text: string }>;
    isError?: boolean;
  };
  expect(result.isError).not.toBe(true);
  return JSON.parse(result.content[0]!.text) as T;
}

function responseAt(
  messages: Array<Record<string, unknown>>,
  index: number,
): Record<string, unknown> {
  const message = messages[index];
  expect(message).toBeTruthy();
  return message!;
}

function withoutCodeWikiEnv(env: NodeJS.ProcessEnv): NodeJS.ProcessEnv {
  return Object.fromEntries(
    Object.entries(env).filter(([key]) => !key.startsWith("CODEWIKI_")),
  );
}
