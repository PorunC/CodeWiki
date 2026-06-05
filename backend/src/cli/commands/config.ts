import { Option, type Command } from "commander";
import { existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { getSettings } from "../../config.js";
import { configPayload, llmModelsPayload } from "../../presenters/payloads.js";
import {
  codewikiValues,
  ensureEnvFile,
  LLM_PROFILES,
  llmProfileKey,
  maskConfigValues,
  parseEnvAssignment,
  readEnvValues,
  validateEnvKey,
  writeEnvValues,
} from "../../services/envConfig.js";
import { formatConfig } from "../formatters.js";
import { output, runCli } from "../runtime.js";

type ConfigOptions = {
  apiKey?: string;
  baseLanguage?: string;
  databaseUrl?: string;
  endpoint?: string;
  configFile?: string;
  envFile?: string;
  get?: string[];
  init?: boolean;
  json?: boolean;
  list?: boolean;
  maxTokens?: string;
  model?: string;
  path?: boolean;
  profile: string;
  providerType?: string;
  set?: string[];
  showSecrets?: boolean;
  translationLanguages?: string;
};

export function registerConfigCommands(program: Command): void {
  const config = program
    .command("config")
    .description("Inspect or update TypeScript backend configuration")
    .option(
      "--config-file <path>",
      "Environment file to read or update",
      ".env",
    )
    .option("--init", "Create the env file from defaults")
    .option("--path", "Print the resolved env file path")
    .option("--list", "List configured CODEWIKI_* values from the env file")
    .option("--get <key>", "Print one env variable", collect, [])
    .option(
      "--set <assignment>",
      "Set an env variable as KEY=VALUE",
      collect,
      [],
    )
    .addOption(
      new Option(
        "--profile <profile>",
        "LLM profile used by model/provider/endpoint/API key options",
      )
        .choices([...LLM_PROFILES])
        .default("default"),
    )
    .option("--model <model>", "Set the selected LLM profile model")
    .option(
      "--provider-type <type>",
      "Set the selected LLM profile provider type",
    )
    .option("--endpoint <url>", "Set the selected LLM profile endpoint")
    .option("--api-key <key>", "Set the selected LLM profile API key")
    .option(
      "--max-tokens <tokens>",
      "Set the selected LLM profile max output tokens",
    )
    .option("--base-language <language>", "Set CODEWIKI_WIKI_BASE_LANGUAGE")
    .option(
      "--translation-languages <languages>",
      "Set CODEWIKI_WIKI_TRANSLATION_LANGUAGES",
    )
    .option("--database-url <url>", "Set CODEWIKI_DATABASE_URL")
    .option("--show-secrets", "Do not mask secret values in command output")
    .option("--json", "Print JSON output")
    .action((options: ConfigOptions, command: Command) => {
      runCli(() => {
        handleConfigCommand(withGlobalConfigOptions(options, command));
      });
    });

  config
    .command("list")
    .option("--json", "Print JSON output")
    .action((options: { json?: boolean }) => {
      runCli(() => {
        const payload = configPayload(getSettings());
        output(options.json, payload, formatConfig(payload));
      });
    });

  config
    .command("models")
    .option("--json", "Print JSON output")
    .action((options: { json?: boolean }) => {
      runCli(() => {
        const payload = llmModelsPayload(getSettings());
        output(options.json, payload, JSON.stringify(payload, null, 2));
      });
    });
}

function handleConfigCommand(options: ConfigOptions): void {
  const envFile = resolve(options.configFile ?? options.envFile ?? ".env");
  const updates = configUpdates(options);
  const hasReadAction =
    Boolean(options.path) ||
    Boolean(options.list) ||
    Boolean(options.get?.length);
  const hasWriteAction =
    Boolean(options.init) || Object.keys(updates).length > 0;

  if (!hasReadAction && !hasWriteAction) {
    const payload = configPayload(getSettings());
    output(options.json, payload, formatConfig(payload));
    return;
  }

  const created = hasWriteAction
    ? ensureEnvFile(envFile, defaultExampleFile())
    : false;
  if (Object.keys(updates).length > 0) {
    writeEnvValues(envFile, updates);
  }

  const values = readEnvValues(envFile);
  if (
    options.path &&
    !options.list &&
    !options.get?.length &&
    !hasWriteAction
  ) {
    const payload = { env_file: envFile, exists: existsSync(envFile) };
    output(options.json, payload, envFile);
    return;
  }
  if (options.get?.length) {
    const selected = Object.fromEntries(
      options.get.map((key) => {
        const validated = validateEnvKey(key);
        return [validated, values[validated] ?? ""];
      }),
    );
    outputConfigValues(selected, {
      json: options.json,
      showSecrets: options.showSecrets,
    });
    return;
  }
  if (options.list) {
    outputConfigValues(codewikiValues(values), {
      envFile,
      json: options.json,
      showSecrets: options.showSecrets,
    });
    return;
  }

  outputConfigUpdate(envFile, created, updates, {
    json: options.json,
    showSecrets: options.showSecrets,
  });
}

function configUpdates(options: ConfigOptions): Record<string, string> {
  const updates: Record<string, string> = {};
  for (const rawAssignment of options.set ?? []) {
    const assignment = parseEnvAssignment(rawAssignment);
    updates[assignment.key] = assignment.value;
  }

  const profile = options.profile;
  const profileOptions: Record<string, string | undefined> = {
    MODEL: options.model,
    PROVIDER_TYPE: options.providerType,
    ENDPOINT: options.endpoint,
    API_KEY: options.apiKey,
    MAX_TOKENS: normalizeMaxTokens(options.maxTokens),
  };
  for (const [field, value] of Object.entries(profileOptions)) {
    if (value !== undefined) {
      updates[llmProfileKey(profile, field)] = value;
    }
  }
  if (options.baseLanguage !== undefined) {
    updates.CODEWIKI_WIKI_BASE_LANGUAGE = options.baseLanguage;
  }
  if (options.translationLanguages !== undefined) {
    updates.CODEWIKI_WIKI_TRANSLATION_LANGUAGES = options.translationLanguages;
  }
  if (options.databaseUrl !== undefined) {
    getSettings({ CODEWIKI_DATABASE_URL: options.databaseUrl });
    updates.CODEWIKI_DATABASE_URL = options.databaseUrl;
  }
  return updates;
}

function withGlobalConfigOptions(
  options: ConfigOptions,
  command: Command,
): ConfigOptions {
  if (options.databaseUrl !== undefined) {
    return options;
  }
  const globals = command.optsWithGlobals<{ databaseUrl?: string }>();
  if (globals.databaseUrl === undefined) {
    return options;
  }
  return { ...options, databaseUrl: globals.databaseUrl };
}

function normalizeMaxTokens(value: string | undefined): string | undefined {
  if (value === undefined) {
    return undefined;
  }
  const parsed = Number.parseInt(value, 10);
  if (!Number.isInteger(parsed) || parsed < 0) {
    throw new Error(`Max tokens must be a non-negative integer, got ${value}`);
  }
  return String(parsed);
}

function outputConfigUpdate(
  envFile: string,
  created: boolean,
  updates: Record<string, string>,
  options: { json?: boolean | undefined; showSecrets?: boolean | undefined },
): void {
  const payload = {
    env_file: envFile,
    created,
    updated: maskConfigValues(updates, { showSecrets: options.showSecrets }),
  };
  if (options.json) {
    output(true, payload, "");
    return;
  }
  if (created) {
    process.stdout.write(`Created ${envFile}\n`);
  }
  if (Object.keys(updates).length === 0) {
    process.stdout.write(`No changes made to ${envFile}\n`);
    return;
  }
  process.stdout.write(
    `Updated ${envFile}\n${formatKeyValues(payload.updated)}\n`,
  );
}

function outputConfigValues(
  values: Record<string, string>,
  options: {
    envFile?: string;
    json?: boolean | undefined;
    showSecrets?: boolean | undefined;
  },
): void {
  const masked = maskConfigValues(values, { showSecrets: options.showSecrets });
  if (options.json) {
    const payload: Record<string, unknown> = { values: masked };
    if (options.envFile) {
      payload.env_file = options.envFile;
    }
    output(true, payload, "");
    return;
  }
  if (Object.keys(masked).length === 0) {
    process.stdout.write(
      options.envFile
        ? `No CODEWIKI_* values configured in ${options.envFile}.\n`
        : "No values found.\n",
    );
    return;
  }
  process.stdout.write(`${formatKeyValues(masked)}\n`);
}

function formatKeyValues(values: Record<string, string>): string {
  return Object.entries(values)
    .map(([key, value]) => `${key}\t${value}`)
    .join("\n");
}

function defaultExampleFile(): string {
  const packageRoot = resolve(
    dirname(fileURLToPath(import.meta.url)),
    "../../..",
  );
  return resolve(packageRoot, ".env.example");
}

function collect(value: string, previous: string[]): string[] {
  return [...previous, value];
}
