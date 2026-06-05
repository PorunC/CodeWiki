import type { CodeWikiSettings } from "../config.js";
import type { CodeWikiStoreApi } from "../db/types.js";
import type { RepoScanner } from "../scanner/scanner.js";
import type { BackendServices } from "../services/backendServices.js";
import type { JsonObject } from "../types.js";

type Awaitable<T> = T | Promise<T>;

export type ToolHandler = (args: JsonObject) => Awaitable<unknown>;

export type ToolBuildOptions = {
  store: CodeWikiStoreApi;
  scanner: RepoScanner;
  settings: CodeWikiSettings;
  services: BackendServices;
};

export type ToolRuntime = {
  store: CodeWikiStoreApi;
  scanner: RepoScanner;
  settings: CodeWikiSettings;
  services: BackendServices;
};

export class ToolSpec {
  constructor(
    readonly name: string,
    readonly description: string,
    readonly inputSchema: JsonObject,
    readonly handler: ToolHandler,
  ) {}

  payload(): JsonObject {
    return {
      name: this.name,
      description: this.description,
      inputSchema: this.inputSchema,
    };
  }
}

export function tool(
  name: string,
  description: string,
  inputSchema: JsonObject,
  handler: ToolHandler,
): ToolSpec {
  return new ToolSpec(name, description, inputSchema, handler);
}

export function objectSchema(
  properties: JsonObject,
  required: string[] = [],
): JsonObject {
  return {
    type: "object",
    properties,
    required,
    additionalProperties: false,
  };
}

export function repoSelectorSchema(): JsonObject {
  return {
    type: "string",
    description: "Repo id, id prefix, registered name, path, or Git URL.",
  };
}

export function symbolSchema(): JsonObject {
  return { type: "string", description: "Symbol name or graph node id." };
}

export function searchFilters(args: JsonObject): {
  types?: string[];
  languages?: string[];
  pathFilters?: string[];
  nameFilters?: string[];
  limit?: number;
} {
  const filters: {
    types?: string[];
    languages?: string[];
    pathFilters?: string[];
    nameFilters?: string[];
    limit?: number;
  } = { limit: intArg(args, "limit", 20) };
  const type = optionalString(args, "type");
  const language = optionalString(args, "language");
  const path = optionalString(args, "path");
  const name = optionalString(args, "name");
  if (type) {
    filters.types = [type];
  }
  if (language) {
    filters.languages = [language];
  }
  if (path) {
    filters.pathFilters = [path];
  }
  if (name) {
    filters.nameFilters = [name];
  }
  return filters;
}

export function requiredString(args: JsonObject, key: string): string {
  const value = args[key];
  if (typeof value !== "string" || !value.trim()) {
    throw new Error(`Argument '${key}' must be a non-empty string.`);
  }
  return value.trim();
}

export function optionalString(args: JsonObject, key: string): string | null {
  const value = args[key];
  if (value === undefined || value === null) {
    return null;
  }
  if (typeof value !== "string") {
    throw new Error(`Argument '${key}' must be a string.`);
  }
  return value.trim() || null;
}

export function intArg(
  args: JsonObject,
  key: string,
  fallback: number,
): number {
  const value = args[key] ?? fallback;
  if (typeof value !== "number" || !Number.isInteger(value)) {
    throw new Error(`Argument '${key}' must be an integer.`);
  }
  return value;
}

export function boolArg(
  args: JsonObject,
  key: string,
  fallback: boolean,
): boolean {
  const value = args[key] ?? fallback;
  if (typeof value !== "boolean") {
    throw new Error(`Argument '${key}' must be a boolean.`);
  }
  return value;
}

export function stringListArg(args: JsonObject, key: string): string[] {
  const value = args[key];
  if (
    !Array.isArray(value) ||
    !value.every((item): item is string => typeof item === "string")
  ) {
    throw new Error(`Argument '${key}' must be a list of strings.`);
  }
  return value;
}

export function languageArg(args: JsonObject): string {
  return optionalString(args, "language") ?? "en";
}

export function maybeMap<T>(
  value: T | null,
  mapper: (value: T) => JsonObject,
): JsonObject | null {
  return value ? mapper(value) : null;
}
