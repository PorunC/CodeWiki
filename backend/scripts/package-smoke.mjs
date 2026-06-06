#!/usr/bin/env node
import { spawnSync } from "node:child_process";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { packageSmokeProcessEnv } from "./package-smoke-env.mjs";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const packageRoot = resolve(scriptDir, "..");
const packageJson = JSON.parse(
  readFileSync(join(packageRoot, "package.json"), "utf8"),
);
const packageImportName = packageJson.name;
const workRoot = mkdtempSync(join(tmpdir(), "codewiki-package-smoke-"));
const packDir = join(workRoot, "pack");
const installDir = join(workRoot, "install");
const npmCacheDir = join(workRoot, "npm-cache");
const installedPackageRoot = join(
  installDir,
  "node_modules",
  ...packageJson.name.split("/"),
);
const sampleRepo = join(workRoot, "sample-repo");
const databasePath = join(workRoot, "data", "codewiki.sqlite3");
const smokeProcessEnv = packageSmokeProcessEnv(process.env, npmCacheDir);
const smokeEnv = {
  ...smokeProcessEnv,
  CODEWIKI_DATABASE_URL: `sqlite:///${databasePath}`,
  CODEWIKI_STORAGE_DIR: join(workRoot, "storage"),
};
const REQUIRED_MCP_TOOLS = [
  "codewiki_analyze",
  "codewiki_ask",
  "codewiki_communities_list",
  "codewiki_communities_name",
  "codewiki_context",
  "codewiki_files_tree",
  "codewiki_graph_affected",
  "codewiki_graph_callees",
  "codewiki_graph_callers",
  "codewiki_graph_dump",
  "codewiki_graph_explore",
  "codewiki_graph_impact",
  "codewiki_graph_node_read",
  "codewiki_graph_search",
  "codewiki_graph_status",
  "codewiki_graphrag_build",
  "codewiki_health",
  "codewiki_llm_models",
  "codewiki_node",
  "codewiki_repo_add",
  "codewiki_repo_delete",
  "codewiki_repo_scan",
  "codewiki_repos_list",
  "codewiki_retrieve_context",
  "codewiki_runs_list",
  "codewiki_trace",
  "codewiki_update",
  "codewiki_wiki_catalog_generate",
  "codewiki_wiki_page_read",
  "codewiki_wiki_page_regenerate",
  "codewiki_wiki_pages_generate",
  "codewiki_wiki_pages_list",
  "codewiki_wiki_pages_update",
  "codewiki_wiki_translate",
];

prepareWorkspace();
prepareSampleRepo();

try {
  const tarballPath = packPackage();
  installPackage(tarballPath);
  checkPackageMetadata();
  checkCliBinaries();
  checkConfigWorkflow();
  const { add, retrieval } = checkRepositoryWorkflow();
  checkLiteCliWorkflow();
  checkPersistedGraphRagTrace(add.id, retrieval.trace_id);
  checkLibraryExports();
  checkPackagedStaticFrontend();
  checkMcpEntrypoints();

  console.log(
    `Package smoke test passed for ${packageJson.name}@${packageJson.version}.`,
  );
} finally {
  if (process.env.CODEWIKI_KEEP_PACKAGE_SMOKE !== "1") {
    rmSync(workRoot, { recursive: true, force: true });
  } else {
    console.log(`Kept smoke test workspace: ${workRoot}`);
  }
}

function prepareWorkspace() {
  mkdirSync(packDir, { recursive: true });
  mkdirSync(installDir, { recursive: true });
}

function prepareSampleRepo() {
  mkdirSync(join(sampleRepo, "src"), { recursive: true });
  writeFileSync(join(sampleRepo, "README.md"), "# Smoke Repo\n");
  writeFileSync(
    join(sampleRepo, "src", "main.ts"),
    [
      "import { helper } from './util';",
      "export function run() {",
      "  return helper(41);",
      "}",
      "",
    ].join("\n"),
  );
  writeFileSync(
    join(sampleRepo, "src", "util.ts"),
    "export function helper(x: number) { return x + 1; }\n",
  );
}

function packPackage() {
  console.log("Packing npm tarball...");
  const packResult = run(
    "npm",
    ["pack", "--json", "--pack-destination", packDir],
    {
      cwd: packageRoot,
      quiet: true,
    },
  );
  assertPackageContents(packedFilePaths(packResult.stdout));
  const tarball = readdirSync(packDir).find((item) => item.endsWith(".tgz"));
  assert(tarball, "npm pack did not produce a tarball.");
  return join(packDir, tarball);
}

function installPackage(tarballPath) {
  console.log("Installing tarball in a clean temporary project...");
  run("npm", ["init", "-y"], { cwd: installDir, quiet: true });
  run("npm", ["install", tarballPath], { cwd: installDir, quiet: true });
}

function checkPackageMetadata() {
  console.log("Checking package metadata...");
  const installedPackageJson = JSON.parse(
    readFileSync(join(installedPackageRoot, "package.json"), "utf8"),
  );
  assert(
    installedPackageJson.main === "dist/index.js",
    `package main points to ${installedPackageJson.main}`,
  );
  assert(
    installedPackageJson.types === "dist/index.d.ts",
    `package types points to ${installedPackageJson.types}`,
  );
}

function checkCliBinaries() {
  console.log("Checking CLI binaries...");
  assert(
    existsSync(
      join(installedPackageRoot, "scripts", "verify-release-version.mjs"),
    ),
    "release version verifier was not included in the npm package.",
  );
  const releaseVerify = run(
    "npm",
    ["--prefix", installedPackageRoot, "run", "release:verify"],
    {
      env: {
        ...smokeProcessEnv,
        CODEWIKI_RELEASE_VERSION: packageJson.version,
      },
      quiet: true,
    },
  );
  assert(
    releaseVerify.stdout.includes(
      `Release version verified for ${packageJson.name}@${packageJson.version}.`,
    ),
    "release version verifier did not accept the package version.",
  );
  const codewikiVersion = execPackageBin([
    "codewiki",
    "--version",
  ]).stdout.trim();
  const backendVersion = execPackageBin([
    "codewiki-backend",
    "--version",
  ]).stdout.trim();
  assert(
    codewikiVersion === packageJson.version,
    `codewiki --version returned ${codewikiVersion}`,
  );
  assert(
    backendVersion === packageJson.version,
    `codewiki-backend --version returned ${backendVersion}`,
  );
  const help = execPackageBin(["codewiki", "--help"]).stdout;
  assert(
    help.includes("serve") && help.includes("repos"),
    "codewiki --help is missing expected commands.",
  );
}

function checkConfigWorkflow() {
  console.log("Checking installed config workflow...");
  const configRoot = join(workRoot, "config-project");
  const configEnvFile = join(configRoot, ".env");
  const configDatabaseUrl = `sqlite:///${join(configRoot, "configured.sqlite3")}`;
  const configEnv = withoutCodeWikiEnv(smokeProcessEnv);
  mkdirSync(configRoot, { recursive: true });
  const configured = JSON.parse(
    execPackageBin(
      [
        "codewiki",
        "config",
        "--config-file",
        configEnvFile,
        "--set",
        "CODEWIKI_APP_NAME=Packaged Wiki",
        "--database-url",
        configDatabaseUrl,
        "--profile",
        "page",
        "--model",
        "openai/page",
        "--api-key",
        "packaged-secret",
        "--json",
      ],
      { cwd: configRoot, env: configEnv },
    ).stdout,
  );
  assert(
    configured.created === true && configured.env_file === configEnvFile,
    "codewiki config did not create the requested env file.",
  );
  assert(
    configured.updated?.CODEWIKI_LLM__PROFILES__PAGE__API_KEY === "********",
    "codewiki config did not mask API keys in output.",
  );
  const listedConfig = JSON.parse(
    execPackageBin(
      [
        "codewiki",
        "config",
        "--config-file",
        configEnvFile,
        "--get",
        "CODEWIKI_LLM__PROFILES__PAGE__API_KEY",
        "--show-secrets",
        "--json",
      ],
      { cwd: configRoot, env: configEnv },
    ).stdout,
  );
  assert(
    listedConfig.values?.CODEWIKI_LLM__PROFILES__PAGE__API_KEY ===
      "packaged-secret",
    "codewiki config did not preserve the stored API key.",
  );
  const configImportCheck = run(
    "node",
    [
      "--input-type=module",
      "-e",
      [
        `const { environmentWithDotEnv, getSettings, readEnvValues } = await import(${JSON.stringify(packageImportName)});`,
        `const envFile = ${JSON.stringify(configEnvFile)};`,
        "const settings = getSettings(environmentWithDotEnv({}, envFile));",
        "if (settings.appName !== 'Packaged Wiki') throw new Error(`Unexpected app name ${settings.appName}`);",
        `if (settings.databaseUrl !== ${JSON.stringify(configDatabaseUrl)}) throw new Error(\`Unexpected database URL ${"${settings.databaseUrl}"}\`);`,
        "if (settings.llm.profiles.page?.model !== 'openai/page') throw new Error('Missing page model from .env');",
        "if (settings.llm.profiles.page?.api_key !== 'packaged-secret') throw new Error('Missing page API key from .env');",
        "const values = readEnvValues(envFile);",
        "if (values.CODEWIKI_APP_NAME !== 'Packaged Wiki') throw new Error('readEnvValues did not parse the env file');",
        "console.log(settings.appName);",
      ].join(" "),
    ],
    { cwd: installDir, env: configEnv, quiet: true },
  );
  assert(
    configImportCheck.stdout.includes("Packaged Wiki"),
    "installed config import check did not read the env file.",
  );
}

function checkRepositoryWorkflow() {
  console.log("Checking installed repository workflow...");
  const add = JSON.parse(
    execPackageBin([
      "codewiki",
      "--database-url",
      smokeEnv.CODEWIKI_DATABASE_URL,
      "repos",
      "add",
      sampleRepo,
      "--name",
      "smoke",
      "--json",
    ]).stdout,
  );
  assert(
    add.id && add.name === "smoke",
    "codewiki repos add did not return the registered repo.",
  );
  const analysis = JSON.parse(
    execPackageBin([
      "codewiki",
      "--database-url",
      smokeEnv.CODEWIKI_DATABASE_URL,
      "analyze",
      "smoke",
      "--force",
      "--progress",
      "--no-community-summaries",
      "--json",
    ]).stdout,
  );
  assert(analysis.status === "done", `analysis status was ${analysis.status}`);
  assert(
    analysis.node_count >= 4,
    `analysis produced too few nodes: ${analysis.node_count}`,
  );
  const currentDirectoryAnalysis = JSON.parse(
    execPackageBin(
      [
        "codewiki",
        "--database-url",
        smokeEnv.CODEWIKI_DATABASE_URL,
        "analyze",
        "--json",
      ],
      {
        cwd: sampleRepo,
      },
    ).stdout,
  );
  assert(
    currentDirectoryAnalysis.repo_id === add.id,
    "codewiki analyze without a repo did not reuse the current directory repository.",
  );
  assert(
    currentDirectoryAnalysis.node_count >= 4,
    `current-directory analysis produced too few nodes: ${currentDirectoryAnalysis.node_count}`,
  );
  const generatedCatalog = JSON.parse(
    execPackageBin([
      "codewiki",
      "--database-url",
      smokeEnv.CODEWIKI_DATABASE_URL,
      "wiki",
      "catalog",
      "smoke",
      "--json",
    ]).stdout,
  );
  assert(
    generatedCatalog.title === "smoke Wiki",
    `wiki catalog title was ${generatedCatalog.title}`,
  );
  assert(
    Array.isArray(generatedCatalog.validation_errors) &&
      generatedCatalog.validation_errors.length === 0,
    "wiki catalog did not include an empty validation_errors array.",
  );
  assert(
    generatedCatalog.structure?.items?.length >= 1,
    "wiki catalog did not include catalog items.",
  );
  const generatedWiki = JSON.parse(
    execPackageBin([
      "codewiki",
      "--database-url",
      smokeEnv.CODEWIKI_DATABASE_URL,
      "wiki",
      "pages",
      "smoke",
      "--json",
    ]).stdout,
  );
  assert(
    generatedWiki.page_count >= 1,
    `wiki pages generated too few pages: ${generatedWiki.page_count}`,
  );
  const firstSlug = generatedWiki.pages?.[0]?.slug;
  assert(firstSlug, "wiki pages did not return a page slug.");

  writeFileSync(
    join(sampleRepo, "src", "util.ts"),
    [
      "export function helper(x: number) { return x + 1; }",
      "export function double(x: number) { return x * 2; }",
      "",
    ].join("\n"),
  );
  const repositoryUpdate = JSON.parse(
    execPackageBin([
      "codewiki",
      "--database-url",
      smokeEnv.CODEWIKI_DATABASE_URL,
      "update",
      "smoke",
      "--json",
    ]).stdout,
  );
  assert(
    repositoryUpdate.status === "done",
    `repository update status was ${repositoryUpdate.status}`,
  );
  assert(
    repositoryUpdate.mode === "typescript_update",
    `repository update mode was ${repositoryUpdate.mode}`,
  );
  assert(
    repositoryUpdate.plan?.changed_files?.includes("src/util.ts"),
    "repository update did not report src/util.ts as changed.",
  );
  assert(
    repositoryUpdate.plan?.affected_files?.includes("src/util.ts"),
    "repository update did not report src/util.ts as affected.",
  );
  assert(
    repositoryUpdate.wiki_regeneration?.generated_pages?.length >= 1,
    "repository update did not regenerate wiki pages.",
  );
  const updatedSearch = JSON.parse(
    execPackageBin([
      "codewiki",
      "--database-url",
      smokeEnv.CODEWIKI_DATABASE_URL,
      "graph",
      "search",
      "double",
      "smoke",
      "--json",
    ]).stdout,
  );
  assert(
    updatedSearch.results?.some((hit) => hit.node?.name === "double"),
    "repository update did not index the new double symbol.",
  );

  const updatedWiki = JSON.parse(
    execPackageBin([
      "codewiki",
      "--database-url",
      smokeEnv.CODEWIKI_DATABASE_URL,
      "wiki",
      "update",
      "smoke",
      "--json",
    ]).stdout,
  );
  assert(
    updatedWiki.status === "updated" || updatedWiki.status === "up_to_date",
    `wiki update status was ${updatedWiki.status}.`,
  );
  assert(
    (updatedWiki.generated_pages?.length ?? 0) >= 1 ||
      (updatedWiki.reused_count ?? 0) >= 1,
    "wiki update did not generate or reuse any pages.",
  );
  const regeneratedPage = JSON.parse(
    execPackageBin([
      "codewiki",
      "--database-url",
      smokeEnv.CODEWIKI_DATABASE_URL,
      "wiki",
      "page",
      firstSlug,
      "smoke",
      "--json",
    ]).stdout,
  );
  assert(
    regeneratedPage.slug === firstSlug,
    "wiki page did not regenerate the requested slug.",
  );
  const translatedWiki = JSON.parse(
    execPackageBin([
      "codewiki",
      "--database-url",
      smokeEnv.CODEWIKI_DATABASE_URL,
      "wiki",
      "translate",
      "zh",
      "smoke",
      "--json",
    ]).stdout,
  );
  assert(
    translatedWiki.target_language === "zh",
    "wiki translate did not return the target language.",
  );
  assert(
    translatedWiki.page_count >= 1,
    "wiki translate did not copy generated pages.",
  );
  const retrieval = JSON.parse(
    execPackageBin([
      "codewiki",
      "--database-url",
      smokeEnv.CODEWIKI_DATABASE_URL,
      "graphrag",
      "retrieve",
      "helper",
      "smoke",
      "--json",
    ]).stdout,
  );
  assert(retrieval.trace_id, "graphrag retrieve did not return a trace id.");
  assert(
    retrieval.query === "helper",
    `graphrag retrieve query was ${retrieval.query}`,
  );
  assert(
    retrieval.source_chunks?.some((chunk) => chunk.file_path === "src/util.ts"),
    "graphrag retrieve did not return the expected source chunk.",
  );
  return { add, retrieval };
}

function checkLiteCliWorkflow() {
  console.log("Checking installed Lite CLI workflow...");
  const liteIndex = JSON.parse(
    execPackageBin(["codewiki", "lite", "index", sampleRepo, "--json"]).stdout,
  );
  assert(
    liteIndex.status === "done",
    `lite index status was ${liteIndex.status}`,
  );
  assert(
    liteIndex.node_count >= 4,
    `lite index produced too few nodes: ${liteIndex.node_count}`,
  );
  assert(
    liteIndex.database_path ===
      join(sampleRepo, ".codewiki", "codewiki-lite.sqlite3"),
    `lite index used unexpected database path: ${liteIndex.database_path}`,
  );
  const liteStatus = JSON.parse(
    execPackageBin(["codewiki", "lite", "status", sampleRepo, "--json"]).stdout,
  );
  assert(
    liteStatus.node_count === liteIndex.node_count,
    "lite status did not read the indexed graph.",
  );
  assert(
    liteStatus.file_count >= 3,
    `lite status reported too few files: ${liteStatus.file_count}`,
  );
  const liteQuery = JSON.parse(
    execPackageBin([
      "codewiki",
      "lite",
      "query",
      "helper",
      sampleRepo,
      "--json",
    ]).stdout,
  );
  assert(
    liteQuery.results?.some(
      (hit) =>
        hit.node?.name === "helper" && hit.node?.file_path === "src/util.ts",
    ),
    "lite query did not return the helper symbol.",
  );
  const liteNode = JSON.parse(
    execPackageBin(["codewiki", "lite", "node", "helper", sampleRepo, "--json"])
      .stdout,
  );
  assert(
    liteNode.node?.name === "helper",
    "lite node did not return the helper symbol.",
  );
  assert(
    liteNode.source_sections?.some((section) =>
      section.content?.includes("helper"),
    ),
    "lite node did not include the helper source section.",
  );
  const liteFiles = JSON.parse(
    execPackageBin([
      "codewiki",
      "lite",
      "files",
      sampleRepo,
      "--source-only",
      "--json",
    ]).stdout,
  );
  assert(
    liteFiles.source === "index",
    "lite files did not read from the index.",
  );
  assert(
    liteFiles.files?.some(
      (file) => file.path === "src/util.ts" && file.is_source === true,
    ),
    "lite files did not list indexed source files.",
  );
  const liteAffected = JSON.parse(
    execPackageBin([
      "codewiki",
      "lite",
      "affected",
      "src/util.ts",
      "--path",
      sampleRepo,
      "--json",
    ]).stdout,
  );
  assert(
    liteAffected.affected_files?.includes("src/util.ts"),
    "lite affected did not include the changed file.",
  );
  assert(
    liteAffected.affected_node_ids?.length >= 1,
    "lite affected did not report affected graph nodes.",
  );
}

function checkPersistedGraphRagTrace(repoId, traceId) {
  const traceCheck = run(
    "node",
    [
      "--input-type=module",
      "-e",
      [
        `const { CodeWikiStore, getSettings } = await import(${JSON.stringify(packageImportName)});`,
        "const store = new CodeWikiStore(getSettings().databasePath);",
        `const trace = store.getRetrievalTrace(${JSON.stringify(repoId)}, ${JSON.stringify(traceId)});`,
        "if (!trace) throw new Error('Missing persisted GraphRAG trace');",
        "if (trace.query !== 'helper') throw new Error(`Unexpected trace query ${trace.query}`);",
        "if (!trace.chunks.some((chunk) => chunk.file_path === 'src/util.ts')) throw new Error('Missing persisted trace chunk');",
        "store.close();",
        "console.log(trace.trace_id);",
      ].join(" "),
    ],
    { cwd: installDir, env: smokeEnv, quiet: true },
  );
  assert(
    traceCheck.stdout.includes(traceId),
    "persisted GraphRAG trace check did not print the trace id.",
  );
}

function checkLibraryExports() {
  console.log("Checking library exports...");
  const importCheck = run(
    "node",
    [
      "--input-type=module",
      "-e",
      [
        `const main = await import(${JSON.stringify(packageImportName)});`,
        `const server = await import(${JSON.stringify(`${packageImportName}/server`)});`,
        `const mcp = await import(${JSON.stringify(`${packageImportName}/mcp`)});`,
        "const required = ['AnalysisService', 'CODEWIKI_VERSION', 'CachedLlmService', 'CodeWikiError', 'CodeWikiStore', 'CodeWikiMCPServer', 'DEFAULT_ENV_CONTENT', 'FALLBACK_MODEL', 'GraphRAGService', 'LLM_PROFILES', 'LLM_TASK_TYPES', 'LlmCallError', 'OpenAiCompatibleLlmGateway', 'RepoScanner', 'RepositoryService', 'codewikiValues', 'conflictError', 'createBackendRuntime', 'createBackendServices', 'createLiteMcpServer', 'createServer', 'defaultEnvFile', 'defaultLlmProfile', 'ensureEnvFile', 'environmentWithDotEnv', 'formatEnvValue', 'isCodeWikiError', 'isOpenAiCompatibleProfile', 'isSecretKey', 'liteDatabasePath', 'llmProfileKey', 'llmTaskProfiles', 'maskConfigValues', 'nameGraphCommunities', 'notFoundError', 'parseEnvAssignment', 'payloadHash', 'profileForTask', 'providerUserIdForRepo', 'readEnvValues', 'retrievalTracePayload', 'startServer', 'testLlmConfiguration', 'validationError', 'validateEnvKey', 'writeEnvValues'];",
        "for (const name of required) { if (!(name in main)) throw new Error(`Missing export ${name}`); }",
        `if (main.CODEWIKI_VERSION !== ${JSON.stringify(packageJson.version)}) throw new Error(\`Unexpected CODEWIKI_VERSION ${"${main.CODEWIKI_VERSION}"}\`);`,
        "const missing = main.notFoundError('Repository', 'smoke');",
        "if (!(missing instanceof main.CodeWikiError) || missing.code !== 'not_found' || !main.isCodeWikiError(missing)) throw new Error('Typed error exports are not usable');",
        "if (main.llmProfileKey('page', 'model') !== 'CODEWIKI_LLM__PROFILES__PAGE__MODEL') throw new Error('Env config exports are not usable');",
        "if (main.providerUserIdForRepo('repo/one') !== 'codewiki-repo-one') throw new Error('LLM cache exports are not usable');",
        "if (typeof main.createBackendServices !== 'function') throw new Error('Missing createBackendServices export');",
        "if (typeof main.createBackendRuntime !== 'function') throw new Error('Missing createBackendRuntime export');",
        "if (typeof server.createServer !== 'function') throw new Error('Missing server export createServer');",
        "if (typeof mcp.CodeWikiMCPServer !== 'function') throw new Error('Missing MCP export CodeWikiMCPServer');",
        "console.log(required.join(','));",
      ].join(" "),
    ],
    { cwd: installDir, env: smokeEnv, quiet: true },
  );
  assert(
    importCheck.stdout.includes("CodeWikiStore"),
    "library export check did not print expected exports.",
  );
}

function checkPackagedStaticFrontend() {
  console.log("Checking packaged static frontend...");
  const staticCheck = run(
    "node",
    [
      "--input-type=module",
      "-e",
      [
        `const { createServer, getSettings } = await import(${JSON.stringify(packageImportName)});`,
        "const app = await createServer({ settings: getSettings() });",
        "const index = await app.inject({ method: 'GET', url: '/' });",
        "if (index.statusCode !== 200) throw new Error(`Unexpected index status ${index.statusCode}`);",
        "if (!String(index.headers['content-type']).includes('text/html')) throw new Error(`Unexpected index content type ${index.headers['content-type']}`);",
        "if (!index.body.includes('<div id=\"root\"></div>')) throw new Error('Packaged frontend index.html was not served.');",
        "const route = await app.inject({ method: 'GET', url: '/graph/example' });",
        "if (route.statusCode !== 200 || !route.body.includes('<div id=\"root\"></div>')) throw new Error('Frontend fallback route was not served.');",
        "const api404 = await app.inject({ method: 'GET', url: '/api/not-found' });",
        "if (api404.statusCode !== 404) throw new Error(`Unexpected API 404 status ${api404.statusCode}`);",
        "if (!String(api404.headers['content-type']).includes('application/json')) throw new Error(`Unexpected API 404 content type ${api404.headers['content-type']}`);",
        "await app.close();",
        "console.log('static-ok');",
      ].join(" "),
    ],
    { cwd: installDir, env: smokeEnv, quiet: true },
  );
  assert(
    staticCheck.stdout.includes("static-ok"),
    "packaged static frontend check did not finish.",
  );
}

function checkMcpEntrypoints() {
  console.log("Checking MCP entrypoints...");
  assertMcpEntrypoint(["codewiki-mcp"]);
  assertMcpEntrypoint(["codewiki", "mcp"]);
  assertLiteMcpEntrypoint([
    "codewiki",
    "mcp",
    "--lite",
    "--path",
    sampleRepo,
    "--no-sync",
  ]);
}

function execPackageBin(binAndArgs, options = {}) {
  return run("npm", ["--prefix", installDir, "exec", "--", ...binAndArgs], {
    cwd: options.cwd ?? installDir,
    env: smokeEnv,
    quiet: true,
    ...options,
  });
}

function assertMcpEntrypoint(binAndArgs) {
  const mcpResponse = execPackageBin(binAndArgs, {
    input:
      JSON.stringify({
        jsonrpc: "2.0",
        id: 1,
        method: "initialize",
        params: { protocolVersion: "2024-11-05" },
      }) +
      "\n" +
      JSON.stringify({ jsonrpc: "2.0", id: 2, method: "tools/list" }) +
      "\n",
  });
  const responses = mcpResponse.stdout
    .trim()
    .split("\n")
    .filter(Boolean)
    .map((line) => JSON.parse(line));
  const label = binAndArgs.join(" ");
  assert(
    responses[0]?.result?.serverInfo?.name === "codewiki",
    `${label} initialize response was invalid.`,
  );
  assert(
    responses[0]?.result?.serverInfo?.version === packageJson.version,
    `${label} initialize version was ${responses[0]?.result?.serverInfo?.version}.`,
  );
  const toolNames = responses[1]?.result?.tools?.map((tool) => tool.name) ?? [];
  assertRequiredMcpTools(label, toolNames);
}

function assertLiteMcpEntrypoint(binAndArgs) {
  const mcpResponse = execPackageBin(binAndArgs, {
    input:
      JSON.stringify({
        jsonrpc: "2.0",
        id: 1,
        method: "initialize",
        params: { protocolVersion: "2024-11-05" },
      }) +
      "\n" +
      JSON.stringify({
        jsonrpc: "2.0",
        id: 2,
        method: "tools/call",
        params: { name: "codewiki_repos_list", arguments: {} },
      }) +
      "\n" +
      JSON.stringify({
        jsonrpc: "2.0",
        id: 3,
        method: "tools/call",
        params: {
          name: "codewiki_analyze",
          arguments: { repo: "sample-repo" },
        },
      }) +
      "\n",
  });
  const responses = mcpResponse.stdout
    .trim()
    .split("\n")
    .filter(Boolean)
    .map((line) => JSON.parse(line));
  const label = binAndArgs.join(" ");
  assert(
    responses[0]?.result?.serverInfo?.name === "codewiki",
    `${label} initialize response was invalid.`,
  );
  assert(
    responses[0]?.result?.serverInfo?.version === packageJson.version,
    `${label} initialize version was ${responses[0]?.result?.serverInfo?.version}.`,
  );
  const repos = toolContent(responses[1]);
  assert(
    repos.length === 1 && repos[0].path === sampleRepo,
    `${label} did not register the lite project path.`,
  );
  const analysis = toolContent(responses[2]);
  assert(
    analysis.status === "done",
    `${label} analysis status was ${analysis.status}`,
  );
  assert(
    analysis.node_count >= 4,
    `${label} produced too few nodes: ${analysis.node_count}`,
  );
  assert(
    existsSync(join(sampleRepo, ".codewiki", "codewiki-lite.sqlite3")),
    `${label} did not create the project-local lite database.`,
  );
}

function toolContent(response) {
  assert(
    response?.result?.isError !== true,
    "MCP tool call returned an error.",
  );
  const text = response?.result?.content?.[0]?.text;
  assert(
    typeof text === "string",
    "MCP tool call did not return text content.",
  );
  return JSON.parse(text);
}

function assertRequiredMcpTools(label, toolNames) {
  const uniqueNames = new Set(toolNames);
  assert(
    uniqueNames.size === toolNames.length,
    `${label} tools/list returned duplicate tool names.`,
  );
  for (const toolName of REQUIRED_MCP_TOOLS) {
    assert(
      uniqueNames.has(toolName),
      `${label} tools/list is missing ${toolName}.`,
    );
  }
}

function packedFilePaths(packOutput) {
  const metadata = JSON.parse(jsonArrayFromNpmOutput(packOutput));
  const files = metadata?.[0]?.files;
  assert(
    Array.isArray(files),
    "npm pack --json did not return a package file list.",
  );
  return files.map((file) => file.path);
}

function jsonArrayFromNpmOutput(output) {
  const start = output.indexOf("[");
  const end = output.lastIndexOf("]");
  assert(
    start >= 0 && end > start,
    "npm pack --json output did not contain JSON metadata.",
  );
  return output.slice(start, end + 1);
}

function assertPackageContents(files) {
  const requiredFiles = [
    "LICENSE",
    "README.md",
    "package.json",
    "dist/index.js",
    "dist/index.d.ts",
    "dist/cli.js",
    "dist/services/envConfig.js",
    "dist/mcp/stdio.js",
    "dist/http/server.js",
    "scripts/check-ports.mjs",
    "scripts/verify-release-version.mjs",
    "static/index.html",
  ];
  for (const file of requiredFiles) {
    assert(
      files.includes(file),
      `npm package is missing required file: ${file}`,
    );
  }

  const forbiddenPrefixes = ["src/", "test/", "coverage/", "node_modules/"];
  for (const file of files) {
    assert(
      !forbiddenPrefixes.some((prefix) => file.startsWith(prefix)),
      `npm package includes development file: ${file}`,
    );
    if (file.startsWith("scripts/")) {
      assert(
        file === "scripts/check-ports.mjs" ||
          file === "scripts/verify-release-version.mjs",
        `npm package includes non-runtime script: ${file}`,
      );
    }
  }
  assert(
    files.some((file) => file.startsWith("static/assets/")),
    "npm package is missing static frontend assets.",
  );
}

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: options.cwd,
    env: options.env ?? smokeProcessEnv,
    input: options.input,
    encoding: "utf8",
    stdio: options.input === undefined ? "pipe" : ["pipe", "pipe", "pipe"],
  });
  if (!options.quiet && result.stdout) {
    process.stdout.write(result.stdout);
  }
  if (!options.quiet && result.stderr) {
    process.stderr.write(result.stderr);
  }
  if (result.error) {
    throw result.error;
  }
  if (result.status !== 0) {
    const output = [result.stdout, result.stderr]
      .filter(Boolean)
      .join("\n")
      .trim();
    const suffix = output ? `\n${output}` : "";
    throw new Error(
      `${command} ${args.join(" ")} exited with ${result.status}${suffix}`,
    );
  }
  return { stdout: result.stdout ?? "", stderr: result.stderr ?? "" };
}

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

function withoutCodeWikiEnv(env) {
  return Object.fromEntries(
    Object.entries(env).filter(([key]) => !key.startsWith("CODEWIKI_")),
  );
}
