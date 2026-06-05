import { createHash } from "node:crypto";
import { basename, join, resolve } from "node:path";

export function isGitUrl(value: string): boolean {
  if (/^[A-Za-z0-9_.-]+@[^:]+:.+/.test(value)) {
    return true;
  }
  try {
    const url = new URL(value);
    return (
      ["http:", "https:", "ssh:", "git:", "file:"].includes(url.protocol) &&
      Boolean(url.pathname)
    );
  } catch {
    return false;
  }
}

export function clonePathForGitUrl(gitUrl: string, storageDir: string): string {
  const digest = createHash("sha1")
    .update(gitUrl.trim().replace(/\/$/, ""))
    .digest("hex")
    .slice(0, 12);
  return join(
    resolve(storageDir),
    "repos",
    `${safeRepoDirName(repoNameFromGitUrl(gitUrl))}-${digest}`,
  );
}

export function repoNameFromGitUrl(gitUrl: string): string {
  const normalized = gitUrl.trim().replace(/\/$/, "");
  const path = /^[A-Za-z0-9_.-]+@[^:]+:.+/.test(normalized)
    ? (normalized.split(":", 2)[1] ?? "")
    : new URL(normalized).pathname;
  const name = basename(path).replace(/\.git$/, "");
  return name || "repository";
}

export function expandHome(value: string): string {
  if (value === "~" || value.startsWith("~/")) {
    return join(process.env.HOME ?? "", value.slice(2));
  }
  return value;
}

function safeRepoDirName(value: string): string {
  return (
    value.replace(/[^A-Za-z0-9._-]+/g, "-").replace(/^[._-]+|[._-]+$/g, "") ||
    "repository"
  ).slice(0, 80);
}
