export type CodeWikiErrorCode = "not_found" | "validation" | "conflict";

export type CodeWikiErrorOptions = {
  cause?: unknown;
  details?: Record<string, unknown>;
  resource?: string;
};

export class CodeWikiError extends Error {
  readonly code: CodeWikiErrorCode;
  readonly details: Record<string, unknown>;
  readonly resource: string | null;

  constructor(
    code: CodeWikiErrorCode,
    message: string,
    options: CodeWikiErrorOptions = {},
  ) {
    super(message, { cause: options.cause });
    this.name = "CodeWikiError";
    this.code = code;
    this.details = options.details ?? {};
    this.resource = options.resource ?? null;
  }
}

export function notFoundError(
  resource: string,
  id: string | number,
): CodeWikiError {
  return new CodeWikiError("not_found", `${resource} not found: ${id}`, {
    resource,
    details: { id },
  });
}

export function validationError(
  message: string,
  details: Record<string, unknown> = {},
): CodeWikiError {
  return new CodeWikiError("validation", message, { details });
}

export function conflictError(
  message: string,
  details: Record<string, unknown> = {},
): CodeWikiError {
  return new CodeWikiError("conflict", message, { details });
}

export function isCodeWikiError(error: unknown): error is CodeWikiError {
  return error instanceof CodeWikiError;
}
