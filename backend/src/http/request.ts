import type { FastifyReply } from "fastify";
import type { CodeWikiStoreApi } from "../db/types.js";
import { CodeWikiError, notFoundError, validationError } from "../errors.js";
import type { RepoDescriptor } from "../types.js";

export type RouteParams = {
  repoId: string;
  runId: string;
  nodeId: string;
  traceId: string;
  slug: string;
};

export type RepositoryReader = Pick<CodeWikiStoreApi, "getRepo">;

export function httpError(
  reply: FastifyReply,
  error: unknown,
  statusCode: number,
): FastifyReply {
  const detail = error instanceof Error ? error.message : String(error);
  return reply.status(statusCode).send({ detail });
}

export function routeError(
  reply: FastifyReply,
  error: unknown,
  fallbackStatusCode = 400,
): FastifyReply {
  return httpError(reply, error, routeErrorStatus(error, fallbackStatusCode));
}

export function routeErrorStatus(
  error: unknown,
  fallbackStatusCode = 400,
): number {
  if (error instanceof CodeWikiError) {
    if (error.code === "not_found") {
      return 404;
    }
    if (error.code === "conflict") {
      return 409;
    }
    return 400;
  }
  return fallbackStatusCode;
}

export async function requireRepo(
  store: RepositoryReader,
  repoId: string,
): Promise<RepoDescriptor> {
  const repo = await store.getRepo(repoId);
  if (!repo) {
    throw notFoundError("Repository", repoId);
  }
  return repo;
}

export async function withRepo<T>(
  reply: FastifyReply,
  store: RepositoryReader,
  repoId: string,
  handler: (repo: RepoDescriptor) => T | Promise<T>,
): Promise<T | FastifyReply> {
  try {
    return await handler(await requireRepo(store, repoId));
  } catch (error) {
    return routeError(reply, error);
  }
}

export function params(value: unknown): RouteParams {
  const raw = isObject(value) ? value : {};
  return {
    repoId: paramString(raw.repoId),
    runId: paramString(raw.runId),
    nodeId: paramString(raw.nodeId),
    traceId: paramString(raw.traceId),
    slug: paramString(raw.slug),
  };
}

export function objectBody(value: unknown): Record<string, unknown> {
  return isObject(value) ? value : {};
}

export function queryObject(value: unknown): Record<string, unknown> {
  return isObject(value) ? value : {};
}

export function stringField(
  value: Record<string, unknown>,
  key: string,
): string {
  const field = value[key];
  if (typeof field !== "string" || !field.trim()) {
    throw validationError(`Missing required field: ${key}`, { field: key });
  }
  return field;
}

export function optionalString(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value : undefined;
}

export function numberQuery(value: unknown, fallback: number): number {
  return numberBody(value, fallback);
}

export function numberBody(value: unknown, fallback: number): number {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string") {
    const parsed = Number.parseInt(value, 10);
    return Number.isFinite(parsed) ? parsed : fallback;
  }
  return fallback;
}

export function boolBody(value: unknown, fallback: boolean): boolean {
  return typeof value === "boolean" ? value : fallback;
}

export function isString(value: unknown): value is string {
  return typeof value === "string";
}

function paramString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
