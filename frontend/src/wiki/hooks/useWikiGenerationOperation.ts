import { useCallback, useSyncExternalStore } from "react";

export type WikiGenerationTask = "pages" | "update" | "page";
export type WikiGenerationStatus = "running" | "success" | "error";

export type WikiGenerationOperation = {
  operationId: number;
  repoId: string;
  language: string;
  task: WikiGenerationTask;
  status: WikiGenerationStatus;
  message: string | null;
  error: string | null;
  startedAt: number;
  completedAt: number | null;
};

type WikiGenerationRecord = {
  snapshot: WikiGenerationOperation;
  promise: Promise<unknown> | null;
  clearTimer: ReturnType<typeof setTimeout> | null;
};

type StartWikiGenerationOptions<T> = {
  repoId: string;
  language: string;
  task: WikiGenerationTask;
  message: string;
  run: () => Promise<T>;
  successMessage: (result: T) => string;
  errorMessage: string;
};

const COMPLETED_OPERATION_TTL_MS = 10 * 60_000;
const RUNNING_OPERATION_TTL_MS = 30 * 60_000;
const STORAGE_KEY = "codewiki:wiki-generation-operations";

let nextOperationId = 1;
const operations = new Map<string, WikiGenerationRecord>();
const listeners = new Set<() => void>();
let hydrated = false;

export function useWikiGenerationOperation(
  repoId: string,
  language: string
): WikiGenerationOperation | null {
  const getSnapshot = useCallback(
    () => getWikiGenerationOperation(repoId, language),
    [language, repoId]
  );
  return useSyncExternalStore(subscribeToWikiGeneration, getSnapshot, getSnapshot);
}

export function startWikiGenerationOperation<T>(
  options: StartWikiGenerationOptions<T>
): Promise<T> {
  hydrateWikiGenerationOperations();
  const key = operationKey(options.repoId, options.language);
  const existing = operations.get(key);
  if (existing?.snapshot.status === "running" && existing.promise) {
    return existing.promise as Promise<T>;
  }

  if (existing?.clearTimer) {
    window.clearTimeout(existing.clearTimer);
  }

  const operationId = nextOperationId;
  nextOperationId += 1;

  const promise = Promise.resolve()
    .then(options.run)
    .then(
      (result) => {
        finishWikiGenerationOperation(key, operationId, {
          status: "success",
          message: options.successMessage(result),
          error: null
        });
        return result;
      },
      (error: unknown) => {
        finishWikiGenerationOperation(key, operationId, {
          status: "error",
          message: null,
          error: error instanceof Error ? error.message : options.errorMessage
        });
        throw error;
      }
    );

  operations.set(key, {
    snapshot: {
      operationId,
      repoId: options.repoId,
      language: options.language,
      task: options.task,
      status: "running",
      message: options.message,
      error: null,
      startedAt: Date.now(),
      completedAt: null
    },
    promise,
    clearTimer: null
  });
  persistWikiGenerationOperations();
  emitWikiGenerationChange();
  return promise;
}

export function clearCompletedWikiGenerationOperation(repoId: string, language: string) {
  hydrateWikiGenerationOperations();
  const key = operationKey(repoId, language);
  const record = operations.get(key);
  if (!record || record.snapshot.status === "running") {
    return;
  }
  if (record.clearTimer) {
    clearTimeout(record.clearTimer);
  }
  operations.delete(key);
  persistWikiGenerationOperations();
  emitWikiGenerationChange();
}

function getWikiGenerationOperation(
  repoId: string,
  language: string
): WikiGenerationOperation | null {
  hydrateWikiGenerationOperations();
  if (!repoId) {
    return null;
  }
  return operations.get(operationKey(repoId, language))?.snapshot ?? null;
}

function finishWikiGenerationOperation(
  key: string,
  operationId: number,
  update: Pick<WikiGenerationOperation, "status" | "message" | "error">
) {
  const record = operations.get(key);
  if (!record || record.snapshot.operationId !== operationId) {
    return;
  }

  const snapshot: WikiGenerationOperation = {
    ...record.snapshot,
    ...update,
    completedAt: Date.now()
  };
  const clearTimer = window.setTimeout(() => {
    const current = operations.get(key);
    if (current?.snapshot.operationId === operationId && current.snapshot.status !== "running") {
      operations.delete(key);
      persistWikiGenerationOperations();
      emitWikiGenerationChange();
    }
  }, COMPLETED_OPERATION_TTL_MS);

  operations.set(key, {
    snapshot,
    promise: null,
    clearTimer
  });
  persistWikiGenerationOperations();
  emitWikiGenerationChange();
}

function hydrateWikiGenerationOperations() {
  if (hydrated || typeof window === "undefined") {
    return;
  }
  hydrated = true;
  const raw = window.sessionStorage.getItem(STORAGE_KEY);
  if (!raw) {
    return;
  }
  try {
    const snapshots = JSON.parse(raw);
    if (!Array.isArray(snapshots)) {
      return;
    }
    const now = Date.now();
    for (const snapshot of snapshots) {
      if (!isWikiGenerationOperation(snapshot)) {
        continue;
      }
      if (snapshot.status === "running" && now - snapshot.startedAt > RUNNING_OPERATION_TTL_MS) {
        snapshot.status = "error";
        snapshot.message = null;
        snapshot.error = "Wiki generation status expired. Refresh or run Generate pages again.";
        snapshot.completedAt = now;
      }
      if (snapshot.completedAt !== null && now - snapshot.completedAt > COMPLETED_OPERATION_TTL_MS) {
        continue;
      }
      operations.set(operationKey(snapshot.repoId, snapshot.language), {
        snapshot,
        promise: null,
        clearTimer: null
      });
      nextOperationId = Math.max(nextOperationId, snapshot.operationId + 1);
    }
  } catch {
    window.sessionStorage.removeItem(STORAGE_KEY);
  }
}

function persistWikiGenerationOperations() {
  if (typeof window === "undefined") {
    return;
  }
  const snapshots = [...operations.values()].map((record) => record.snapshot);
  if (snapshots.length === 0) {
    window.sessionStorage.removeItem(STORAGE_KEY);
    return;
  }
  window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(snapshots));
}

function isWikiGenerationOperation(value: unknown): value is WikiGenerationOperation {
  if (!value || typeof value !== "object") {
    return false;
  }
  const snapshot = value as Partial<WikiGenerationOperation>;
  return (
    typeof snapshot.operationId === "number" &&
    typeof snapshot.repoId === "string" &&
    typeof snapshot.language === "string" &&
    (snapshot.task === "pages" || snapshot.task === "update" || snapshot.task === "page") &&
    (snapshot.status === "running" || snapshot.status === "success" || snapshot.status === "error") &&
    typeof snapshot.startedAt === "number" &&
    (typeof snapshot.completedAt === "number" || snapshot.completedAt === null)
  );
}

function subscribeToWikiGeneration(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function emitWikiGenerationChange() {
  for (const listener of listeners) {
    listener();
  }
}

function operationKey(repoId: string, language: string): string {
  return `${repoId}\u0000${language}`;
}
