import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { CODEWIKI_PACKAGE, CODEWIKI_VERSION } from "../src/version.js";

describe("package metadata", () => {
  it("uses package.json as the single source of truth for runtime version", () => {
    const packageJson = JSON.parse(
      readFileSync(join(import.meta.dirname, "..", "package.json"), "utf8"),
    ) as { name: string; version: string };

    expect(CODEWIKI_PACKAGE.name).toBe(packageJson.name);
    expect(CODEWIKI_VERSION).toBe(packageJson.version);
  });
});
