#!/usr/bin/env node
import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const SEMVER_PATTERN =
  /^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$/;

const scriptDir = dirname(fileURLToPath(import.meta.url));
const packageRoot = resolve(scriptDir, "..");

if (isMainModule()) {
  try {
    const packageJson = JSON.parse(
      readFileSync(join(packageRoot, "package.json"), "utf8"),
    );
    const result = verifyReleaseVersion({
      packageName: packageJson.name,
      packageVersion: packageJson.version,
      refType: process.env.GITHUB_REF_TYPE,
      refName: process.env.GITHUB_REF_NAME,
      requestedVersion: process.env.CODEWIKI_RELEASE_VERSION,
    });
    process.stdout.write(`${result.message}\n`);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    process.stderr.write(`Release version check failed: ${message}\n`);
    process.exitCode = 1;
  }
}

export function verifyReleaseVersion({
  packageName,
  packageVersion,
  refType,
  refName,
  requestedVersion,
}) {
  assertSemver(packageVersion, `${packageName ?? "package"} version`);
  const checks = releaseVersionChecks({ refType, refName, requestedVersion });
  if (!checks.length) {
    throw new Error(
      "No release version provided. Publish from a v-prefixed Git tag or set CODEWIKI_RELEASE_VERSION.",
    );
  }

  for (const check of checks) {
    assertSemver(check.version, check.source);
    if (check.version !== packageVersion) {
      throw new Error(
        `${check.source} (${check.version}) does not match ${packageName}@${packageVersion}.`,
      );
    }
  }

  return {
    verified: true,
    packageName,
    packageVersion,
    message: `Release version verified for ${packageName}@${packageVersion}.`,
  };
}

export function releaseVersionChecks({ refType, refName, requestedVersion }) {
  const checks = [];
  if (refType === "tag" && refName) {
    checks.push({
      source: `Git tag ${refName}`,
      version: normalizeVersion(refName),
    });
  }
  if (requestedVersion?.trim()) {
    checks.push({
      source: "Requested release version",
      version: normalizeVersion(requestedVersion),
    });
  }
  return checks;
}

function normalizeVersion(value) {
  return value.trim().replace(/^v(?=\d)/, "");
}

function assertSemver(value, label) {
  if (typeof value !== "string" || !SEMVER_PATTERN.test(value)) {
    throw new Error(
      `${label} must be a semver version, got ${JSON.stringify(value)}.`,
    );
  }
}

function isMainModule() {
  return process.argv[1]
    ? fileURLToPath(import.meta.url) === process.argv[1]
    : false;
}
