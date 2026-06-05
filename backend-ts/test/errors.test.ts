import { describe, expect, it } from "vitest";
import {
  CodeWikiError,
  conflictError,
  isCodeWikiError,
  notFoundError,
  validationError,
} from "../src/errors.js";
import { routeErrorStatus } from "../src/http/request.js";

describe("typed CodeWiki errors", () => {
  it("carries stable error codes, resource metadata, and HTTP status mapping", () => {
    const missing = notFoundError("Repository", "repo-id");
    expect(missing).toBeInstanceOf(CodeWikiError);
    expect(isCodeWikiError(missing)).toBe(true);
    expect(missing).toMatchObject({
      code: "not_found",
      message: "Repository not found: repo-id",
      resource: "Repository",
      details: { id: "repo-id" },
    });
    expect(routeErrorStatus(missing)).toBe(404);

    const invalid = validationError("Missing required field: question", {
      field: "question",
    });
    expect(invalid.code).toBe("validation");
    expect(routeErrorStatus(invalid)).toBe(400);

    const conflict = conflictError("Repository name is ambiguous: app", {
      selector: "app",
    });
    expect(conflict.code).toBe("conflict");
    expect(routeErrorStatus(conflict)).toBe(409);
  });

  it("keeps generic errors on the caller-provided fallback status", () => {
    expect(routeErrorStatus(new Error("plain failure"), 422)).toBe(422);
  });
});
