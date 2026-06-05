import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync } from "node:fs";
import { dirname } from "node:path";

export function gitMetadata(repoPath: string): {
  git_url: string | null;
  commit_hash: string | null;
} {
  const commit_hash = gitOutput(repoPath, ["rev-parse", "HEAD"]);
  const git_url =
    gitOutput(repoPath, ["config", "--get", "remote.origin.url"]) ??
    gitOutput(repoPath, ["remote", "get-url", "origin"]);
  return { git_url, commit_hash };
}

export function gitListFiles(repoPath: string): string[] | null {
  const tracked = gitOutput(repoPath, ["ls-files"]);
  if (tracked === null) {
    return null;
  }
  const untracked =
    gitOutput(repoPath, ["ls-files", "--others", "--exclude-standard"]) ?? "";
  return [...tracked.split("\n"), ...untracked.split("\n")]
    .map((item) => item.trim())
    .filter(Boolean)
    .sort((left, right) => left.localeCompare(right));
}

export function gitFileCommitTimes(
  repoPath: string,
  filePaths: string[],
): Map<string, string> {
  const result = new Map<string, string>();
  for (const filePath of filePaths) {
    const raw = gitOutput(repoPath, [
      "log",
      "-1",
      "--format=%cI",
      "--",
      filePath,
    ]);
    if (raw) {
      result.set(filePath, raw);
    }
  }
  return result;
}

export function gitClone(gitUrl: string, destination: string): string {
  if (!existsSync(dirname(destination))) {
    mkdirSync(dirname(destination), { recursive: true });
  }
  execFileSync("git", ["clone", "--depth", "1", gitUrl, destination], {
    stdio: ["ignore", "pipe", "pipe"],
  });
  return destination;
}

function gitOutput(repoPath: string, args: string[]): string | null {
  try {
    return execFileSync("git", ["-C", repoPath, ...args], {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
    }).trim();
  } catch {
    return null;
  }
}
