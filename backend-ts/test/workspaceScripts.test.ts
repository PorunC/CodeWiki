import { mkdtempSync, mkdirSync, writeFileSync, existsSync } from "node:fs";
import { readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";

import { clean, CLEAN_PATHS } from "../../scripts/clean.mjs";
import {
  frontendNpmCommand,
  isWindowsToolOnWsl,
} from "../../scripts/frontend-npm.mjs";
import {
  releaseVersionChecks,
  verifyReleaseVersion,
} from "../scripts/verify-release-version.mjs";
import { packageSmokeProcessEnv } from "../scripts/package-smoke-env.mjs";

describe("workspace Node scripts", () => {
  it("cleans TypeScript backend and frontend build artifacts", () => {
    const root = mkdtempSync(join(tmpdir(), "codewiki-clean-test-"));
    for (const relativePath of CLEAN_PATHS) {
      const target = join(root, relativePath);
      mkdirSync(resolve(target, ".."), { recursive: true });
      writeFileSync(target, "artifact");
    }

    const removed = clean(CLEAN_PATHS, root);

    expect(removed).toEqual(CLEAN_PATHS);
    for (const relativePath of CLEAN_PATHS) {
      expect(existsSync(join(root, relativePath))).toBe(false);
    }
  });

  it("builds frontend npm commands without requiring Python", () => {
    const root = mkdtempSync(join(tmpdir(), "codewiki-frontend-npm-test-"));
    const binDir = join(root, "bin");
    const frontendDir = join(root, "ui");
    const npmPath = join(binDir, "npm");
    mkdirSync(binDir, { recursive: true });
    mkdirSync(frontendDir, { recursive: true });
    writeFileSync(npmPath, "#!/bin/sh\n");

    const command = frontendNpmCommand(["run", "build"], {
      NPM: "npm",
      PATH: binDir,
      FRONTEND_DIR: frontendDir,
    });

    expect(command.ok).toBe(true);
    if (command.ok) {
      expect(command.command).toBe(npmPath);
      expect(command.args).toEqual(["run", "build"]);
      expect(command.frontendDir).toBe(frontendDir);
    }
  });

  it("recognizes Windows npm paths that should be rejected inside WSL", () => {
    expect(isWindowsToolOnWsl("/mnt/c/Program Files/nodejs/npm.cmd")).toBe(
      true,
    );
    expect(isWindowsToolOnWsl("C:\\Program Files\\nodejs\\npm.ps1")).toBe(true);
    expect(isWindowsToolOnWsl("/usr/bin/npm")).toBe(false);
  });

  it("isolates package smoke npm cache in the temporary smoke workspace", () => {
    const env = packageSmokeProcessEnv(
      {
        HOME: "/home/codewiki",
        NPM_CONFIG_CACHE: "/home/codewiki/.npm",
      },
      "/tmp/codewiki-package-smoke/npm-cache",
    );

    expect(env.HOME).toBe("/home/codewiki");
    expect(env.NPM_CONFIG_CACHE).toBe("/tmp/codewiki-package-smoke/npm-cache");
  });

  it("verifies release tags and workflow inputs against the backend package version", () => {
    expect(
      releaseVersionChecks({
        refType: "tag",
        refName: "v0.7.0",
        requestedVersion: "0.7.0",
      }),
    ).toEqual([
      { source: "Git tag v0.7.0", version: "0.7.0" },
      { source: "Requested release version", version: "0.7.0" },
    ]);

    expect(
      verifyReleaseVersion({
        packageName: "codewiki-backend",
        packageVersion: "0.7.0",
        refType: "tag",
        refName: "v0.7.0",
      }),
    ).toMatchObject({
      verified: true,
      packageName: "codewiki-backend",
      packageVersion: "0.7.0",
    });
    expect(
      verifyReleaseVersion({
        packageName: "codewiki-backend",
        packageVersion: "0.7.0",
        requestedVersion: "v0.7.0",
      }).message,
    ).toBe("Release version verified for codewiki-backend@0.7.0.");
  });

  it("rejects npm release versions that do not match the backend package", () => {
    expect(() =>
      verifyReleaseVersion({
        packageName: "codewiki-backend",
        packageVersion: "0.7.0",
        refType: "tag",
        refName: "v0.8.0",
      }),
    ).toThrow("does not match codewiki-backend@0.7.0");
    expect(() =>
      verifyReleaseVersion({
        packageName: "codewiki-backend",
        packageVersion: "0.7.0",
      }),
    ).toThrow("No release version provided");
    expect(() =>
      verifyReleaseVersion({
        packageName: "codewiki-backend",
        packageVersion: "0.7",
        requestedVersion: "0.7",
      }),
    ).toThrow("must be a semver version");
  });

  it("keeps the npm publish workflow guarded by backend, frontend, release, and package checks", () => {
    const workflow = readFileSync(
      resolve(import.meta.dirname, "../../.github/workflows/publish-npm.yml"),
      "utf8",
    );

    expect(workflow).toContain("npm --prefix backend-ts run verify");
    expect(workflow).toContain("npm --prefix frontend run lint");
    expect(workflow).toContain("npm --prefix backend-ts run release:verify");
    expect(workflow).toContain("npm --prefix backend-ts run pack:smoke");
    expect(workflow.indexOf("npm --prefix backend-ts run verify")).toBeLessThan(
      workflow.indexOf("npm publish --provenance --access public"),
    );
    expect(
      workflow.indexOf("npm --prefix backend-ts run release:verify"),
    ).toBeLessThan(
      workflow.indexOf("npm publish --provenance --access public"),
    );
  });

  it("runs npm pack dry-runs through an isolated cache wrapper", () => {
    const root = resolve(import.meta.dirname, "../..");
    const packageJson = JSON.parse(
      readFileSync(resolve(root, "backend-ts/package.json"), "utf8"),
    ) as { scripts?: Record<string, string> };
    const dryRunScript = readFileSync(
      resolve(root, "backend-ts/scripts/package-dry-run.mjs"),
      "utf8",
    );

    expect(packageJson.scripts?.["pack:dry"]).toBe(
      "node scripts/package-dry-run.mjs",
    );
    expect(dryRunScript).toContain("packageSmokeProcessEnv");
    expect(dryRunScript).toContain("npm-cache");
    expect(dryRunScript).toContain('"npm", ["pack", "--dry-run"]');
  });

  it("keeps TypeScript as the default backend and only publishable package", () => {
    const root = resolve(import.meta.dirname, "../..");
    const makefile = readFileSync(resolve(root, "Makefile"), "utf8");
    const pyproject = readFileSync(resolve(root, "pyproject.toml"), "utf8");
    const testWorkflow = readFileSync(
      resolve(root, ".github/workflows/test.yml"),
      "utf8",
    );

    expect(makefile).toContain("BACKEND_DIR := backend-ts");
    expect(makefile).toContain("$(NPM) --prefix $(BACKEND_DIR) test");
    expect(makefile).toContain("$(NPM) --prefix $(BACKEND_DIR) run build");
    expect(makefile).not.toContain("pip install");
    expect(makefile).not.toContain("pytest");

    expect(testWorkflow).toContain("npm --prefix backend-ts run typecheck");
    expect(testWorkflow).toContain("npm --prefix backend-ts test");
    expect(testWorkflow).toContain("npm --prefix backend-ts run pack:smoke");
    expect(testWorkflow).not.toContain("pytest");

    expect(pyproject).not.toMatch(/^\[project\]/m);
    expect(pyproject).not.toMatch(/^\[build-system\]/m);
    expect(pyproject).not.toContain("codewiki =");
    expect(existsSync(resolve(root, "MANIFEST.in"))).toBe(false);
    expect(
      existsSync(resolve(root, ".github/workflows/publish-pypi.yml")),
    ).toBe(false);
  });
});
