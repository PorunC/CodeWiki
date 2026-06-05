import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { getSettings, sqlitePathFromUrl } from "../src/config.js";
import {
  profileForTask,
  testLlmConfiguration,
} from "../src/llm/modelRouter.js";
import { llmModelsPayload } from "../src/presenters/payloads.js";
import {
  codewikiValues,
  environmentWithDotEnv,
  formatEnvValue,
  llmProfileKey,
  maskConfigValues,
  readEnvValues,
  writeEnvValues,
} from "../src/services/envConfig.js";

describe("config", () => {
  it("normalizes Python sqlite URLs", () => {
    expect(
      sqlitePathFromUrl("sqlite+aiosqlite:///./data/codewiki.sqlite3"),
    ).toContain("data/codewiki.sqlite3");
  });

  it("reads host, port, and LLM profile env", () => {
    const settings = getSettings({
      CODEWIKI_DATABASE_URL: "sqlite:///:memory:",
      CODEWIKI_HOST: "0.0.0.0",
      CODEWIKI_PORT: "9000",
      CODEWIKI_LLM__DEFAULT__MODEL: "openai/example",
      CODEWIKI_LLM__DEFAULT__API_KEY: "secret",
    });

    expect(settings.databasePath).toBe(":memory:");
    expect(settings.host).toBe("0.0.0.0");
    expect(settings.port).toBe(9000);
    expect(settings.llm.default.model).toBe("openai/example");
    expect(settings.llm.default.api_key).toBe("secret");
  });

  it("resolves task LLM profiles and offline configuration checks", () => {
    const settings = getSettings({
      CODEWIKI_DATABASE_URL: "sqlite:///:memory:",
      CODEWIKI_LLM__DEFAULT__MODEL: "openai/default",
      CODEWIKI_LLM__DEFAULT__API_KEY: "secret",
      CODEWIKI_LLM__PROFILES__PAGE__MODEL: "openai/page",
      CODEWIKI_LLM__PROFILES__PAGE__MAX_TOKENS: "777",
      CODEWIKI_LLM__PROFILES__COMMUNITY_SUMMARY__MODEL: "anthropic/community",
    });

    expect(profileForTask(settings, "page")).toMatchObject({
      task_type: "page",
      model: "openai/page",
      max_tokens: 777,
      stream: false,
    });
    expect(profileForTask(settings, "cluster")).toMatchObject({
      task_type: "cluster",
      model: "anthropic/community",
      max_tokens: 4096,
      stream: false,
    });
    expect(profileForTask(settings, "qa")).toMatchObject({
      task_type: "qa",
      model: "openai/default",
      stream: true,
    });

    const models = llmModelsPayload(settings);
    expect(models.profiles).toMatchObject({
      catalog: { model: "openai/default", max_tokens: 4096 },
      page: { model: "openai/page", max_tokens: 777 },
      qa: { model: "openai/default", stream: true },
    });
    expect(testLlmConfiguration(settings, { taskType: "qa" })).toMatchObject({
      status: "configured",
      configured: true,
      has_api_key: true,
      stream: true,
    });

    const missingCredentials = getSettings({
      CODEWIKI_DATABASE_URL: "sqlite:///:memory:",
      CODEWIKI_LLM__DEFAULT__MODEL: "openai/default",
    });
    expect(
      testLlmConfiguration(missingCredentials, { taskType: "qa" }),
    ).toMatchObject({
      status: "missing_credentials",
      configured: false,
      has_api_key: false,
    });

    const localEndpoint = getSettings({
      CODEWIKI_DATABASE_URL: "sqlite:///:memory:",
      CODEWIKI_LLM__DEFAULT__MODEL: "local/model",
      CODEWIKI_LLM__DEFAULT__ENDPOINT: "http://127.0.0.1:11434/v1",
    });
    expect(
      testLlmConfiguration(localEndpoint, { taskType: "qa" }),
    ).toMatchObject({
      status: "configured",
      configured: true,
      endpoint: "http://127.0.0.1:11434/v1",
    });
  });

  it("reads, writes, orders, and masks env file configuration", () => {
    const root = mkdtempSync(join(tmpdir(), "codewiki-env-config-"));
    const envFile = join(root, ".env");
    writeFileSync(
      envFile,
      [
        "# Existing config",
        "export CODEWIKI_APP_NAME = Old Wiki",
        "CODEWIKI_LLM__DEFAULT__API_KEY=old-secret",
        "CODEWIKI_EXTRA=value # comment",
        "",
      ].join("\n"),
    );

    writeEnvValues(envFile, {
      CODEWIKI_APP_NAME: "New Wiki",
      CODEWIKI_DATABASE_URL: "sqlite:///./data/configured.sqlite3",
      CODEWIKI_LLM__DEFAULT__API_KEY: "new-secret",
      [llmProfileKey("page", "model")]: "openai/page",
    });

    const content = readFileSync(envFile, "utf8");
    expect(content).toContain('export CODEWIKI_APP_NAME = "New Wiki"');
    expect(content).toContain("CODEWIKI_LLM__DEFAULT__API_KEY=new-secret");
    expect(content).toContain(
      "CODEWIKI_DATABASE_URL=sqlite:///./data/configured.sqlite3",
    );
    expect(readEnvValues(envFile)).toMatchObject({
      CODEWIKI_APP_NAME: "New Wiki",
      CODEWIKI_DATABASE_URL: "sqlite:///./data/configured.sqlite3",
      CODEWIKI_EXTRA: "value",
      CODEWIKI_LLM__DEFAULT__API_KEY: "new-secret",
      CODEWIKI_LLM__PROFILES__PAGE__MODEL: "openai/page",
    });
    expect(maskConfigValues(readEnvValues(envFile))).toMatchObject({
      CODEWIKI_LLM__DEFAULT__API_KEY: "********",
    });
    expect(
      Object.keys(codewikiValues(readEnvValues(envFile))).slice(0, 3),
    ).toEqual([
      "CODEWIKI_APP_NAME",
      "CODEWIKI_DATABASE_URL",
      "CODEWIKI_LLM__DEFAULT__API_KEY",
    ]);
    expect(formatEnvValue("needs quoting")).toBe('"needs quoting"');
  });

  it("merges .env values below process env overrides", () => {
    const root = mkdtempSync(join(tmpdir(), "codewiki-dotenv-"));
    const envFile = join(root, ".env");
    writeFileSync(
      envFile,
      [
        "CODEWIKI_DATABASE_URL=sqlite:///./from-env-file.sqlite3",
        "CODEWIKI_STORAGE_DIR=./storage-from-env-file",
        "CODEWIKI_LLM__DEFAULT__MODEL=openai/env-file",
      ].join("\n"),
    );

    const env = environmentWithDotEnv(
      {
        CODEWIKI_DATABASE_URL: "sqlite:///:memory:",
      },
      envFile,
    );
    const settings = getSettings(env);

    expect(settings.databasePath).toBe(":memory:");
    expect(settings.storageDir).toContain("storage-from-env-file");
    expect(settings.llm.default.model).toBe("openai/env-file");
  });
});
