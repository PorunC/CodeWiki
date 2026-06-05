import type { RepoDescriptor } from "../types.js";

export function sourceUrlBaseForRepo(repo: RepoDescriptor): string | null {
  if (!repo.git_url) {
    return null;
  }
  let normalized = repo.git_url.trim().replace(/\/+$/, "");
  if (normalized.endsWith(".git")) {
    normalized = normalized.slice(0, -4);
  }
  if (normalized.startsWith("git@")) {
    const withoutPrefix = normalized.slice("git@".length);
    const [host, repoPath] = withoutPrefix.split(":", 2);
    if (host && repoPath) {
      normalized = `https://${host}/${repoPath}`;
    }
  }
  const ref = repo.commit_hash || "HEAD";
  if (normalized.includes("gitlab")) {
    return `${normalized}/-/blob/${ref}`;
  }
  if (normalized.includes("bitbucket.org")) {
    return `${normalized}/src/${ref}`;
  }
  return `${normalized}/blob/${ref}`;
}

export function sourceUrlForRange(
  sourceUrlBase: string,
  filePath: string,
  startLine: number,
  endLine: number,
): string {
  const encodedPath = filePath
    .split("/")
    .map((part) => encodeURIComponent(part))
    .join("/");
  return `${sourceUrlBase}/${encodedPath}#L${startLine}-L${endLine}`;
}
