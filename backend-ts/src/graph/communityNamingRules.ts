import { basename } from "node:path";

export const FALLBACK_COMMUNITY_NAME = "Code Area";

export const GENERIC_FILE_LABELS = new Set([
  "",
  "index",
  "main",
  "root",
  "src",
  "source",
  "lib",
  "app",
]);

const GENERIC_COMMUNITY_NAMES = new Set([
  "backend subsystem",
  "frontend subsystem",
  "core subsystem",
  "core",
  "misc",
  "miscellaneous",
  "cluster",
  "community",
]);

export function fileLabel(filePath: string): string {
  const fileName = basename(filePath);
  if (fileName.startsWith("__init__.")) {
    const packageName = packageNameFromPath(filePath);
    return packageName
      ? `${humanizeName(packageName)} Package`
      : "Python Package";
  }
  const stem = fileStem(fileName);
  if (stem.toLowerCase() === "readme") {
    return "Documentation";
  }
  if (stem.toLowerCase() === "index") {
    return humanizeName(
      lastPathPart(filePath.split("/").slice(0, -1).join("/")),
    );
  }
  return humanizeName(stem);
}

export function normalizeCommunityName(
  value: string,
  fallback: string,
): string {
  const name = value
    .replace(/\s+/g, " ")
    .trim()
    .replace(/^(?:community|cluster)\s+\d+\s*[:-]\s*/i, "")
    .slice(0, 80)
    .replace(/^[\s:-]+|[\s:-]+$/g, "");
  return name || fallback;
}

export function nonGenericFallbackName(name: string, index: number): string {
  const fallback = `${FALLBACK_COMMUNITY_NAME} ${index + 1}`;
  const candidate = normalizeCommunityName(name, fallback);
  return isGenericName(candidate) ? fallback : candidate;
}

export function humanizeName(value: string): string {
  return value
    .replace(/^test[_-]/i, "")
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/[_-]+/g, " ")
    .split(/\s+/)
    .filter(Boolean)
    .map((word) =>
      word.toUpperCase() === word
        ? word
        : `${word.slice(0, 1).toUpperCase()}${word.slice(1)}`,
    )
    .join(" ")
    .trim();
}

export function lastPathPart(value: string): string {
  const parts = value.split("/").filter(Boolean);
  return parts.at(-1) ?? value;
}

export function dedupeName(name: string, seenNames: Set<string>): string {
  const trimmed = name.trim() || FALLBACK_COMMUNITY_NAME;
  if (!seenNames.has(trimmed.toLowerCase())) {
    return trimmed;
  }
  let suffix = 2;
  let candidate = `${trimmed} ${suffix}`;
  while (seenNames.has(candidate.toLowerCase())) {
    suffix += 1;
    candidate = `${trimmed} ${suffix}`;
  }
  return candidate;
}

export function isGenericName(name: string): boolean {
  const normalized = name.toLowerCase().replace(/\s+/g, " ").trim();
  return (
    !normalized ||
    GENERIC_FILE_LABELS.has(normalized) ||
    GENERIC_COMMUNITY_NAMES.has(normalized) ||
    /^(?:community|cluster|code area)[\s_:#-]*(?:\d+|n)?$/.test(normalized)
  );
}

function fileStem(fileName: string): string {
  const trimmed = fileName.replace(/^\.+/, "");
  const index = trimmed.lastIndexOf(".");
  return index > 0 ? trimmed.slice(0, index) : trimmed;
}

function packageNameFromPath(filePath: string): string {
  return filePath.split("/").slice(0, -1).at(-1) ?? "";
}
