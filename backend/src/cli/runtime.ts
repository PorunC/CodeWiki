import type { Command } from "commander";
import { readFileSync } from "node:fs";
import { getSettings, type CodeWikiSettings } from "../config.js";
import { createCodeWikiStore } from "../db/factory.js";
import type { CodeWikiStoreApi } from "../db/types.js";
import { RepoScanner } from "../scanner/scanner.js";
import {
  createBackendRuntime,
  type BackendServices,
} from "../services/backendServices.js";

export type JsonOption = {
  json?: boolean;
};

export type CliContext = {
  settings: CodeWikiSettings;
  store: CodeWikiStoreApi;
  scanner: RepoScanner;
  services: BackendServices;
};

export type CliRuntime = {
  context: () => CliContext;
  withDatabaseOverride: () => void;
};

export function createCliRuntime(program: Command): CliRuntime {
  return {
    context: () => createContext(program),
    withDatabaseOverride: () => withDatabaseOverride(program),
  };
}

export function runWithContext(
  runtime: CliRuntime,
  fn: (context: CliContext) => void | Promise<void>,
): Promise<void> {
  return runCliAsync(async () => {
    const context = runtime.context();
    try {
      await fn(context);
    } finally {
      await context.store.close();
    }
  });
}

export function runWithContextAsync(
  runtime: CliRuntime,
  fn: (context: CliContext) => Promise<void>,
): Promise<void> {
  return runCliAsync(async () => {
    const context = runtime.context();
    try {
      await fn(context);
    } finally {
      await context.store.close();
    }
  });
}

export function withDatabaseOverride(program: Command): void {
  const databaseUrl = program.opts<{ databaseUrl?: string }>().databaseUrl;
  if (databaseUrl) {
    process.env.CODEWIKI_DATABASE_URL = databaseUrl;
  }
}

export function readStdinLines(): string[] {
  return readFileSync(0, "utf8")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
}

export function readStdinText(): string {
  return readFileSync(0, "utf8");
}

export function parseLimit(value: string): number {
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 20;
}

export function recordValue(value: unknown): Record<string, unknown> {
  return isRecord(value) ? value : {};
}

export function arrayOfRecords(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value) ? value.filter(isRecord) : [];
}

export function stringArray(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

export function displayString(value: unknown, fallback = ""): string {
  if (typeof value === "string") {
    return value;
  }
  if (
    typeof value === "number" ||
    typeof value === "boolean" ||
    typeof value === "bigint"
  ) {
    return String(value);
  }
  return fallback;
}

export function displayNumber(value: unknown, fallback = 0): string {
  return typeof value === "number" && Number.isFinite(value)
    ? String(value)
    : String(fallback);
}

export function output(
  asJson: boolean | undefined,
  payload: unknown,
  text: string,
): void {
  if (asJson) {
    process.stdout.write(`${JSON.stringify(payload, null, 2)}\n`);
    return;
  }
  process.stdout.write(`${text}${text.endsWith("\n") ? "" : "\n"}`);
}

export function runCli(fn: () => void): void {
  try {
    fn();
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    process.stderr.write(`Error: ${message}\n`);
    process.exitCode = 1;
  }
}

export async function runCliAsync(fn: () => Promise<void>): Promise<void> {
  try {
    await fn();
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    process.stderr.write(`Error: ${message}\n`);
    process.exitCode = 1;
  }
}

function createContext(program: Command): CliContext {
  withDatabaseOverride(program);
  const settings = getSettings();
  const store = createCodeWikiStore(settings.databaseUrl);
  const scanner = new RepoScanner({ storageDir: settings.storageDir });
  return createBackendRuntime({ settings, store, scanner });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
