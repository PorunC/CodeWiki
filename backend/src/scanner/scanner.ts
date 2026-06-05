import { createHash } from "node:crypto";
import {
  existsSync,
  lstatSync,
  mkdirSync,
  readdirSync,
  statSync,
  type Stats,
} from "node:fs";
import { basename, dirname, join, relative, resolve } from "node:path";
import type {
  RepoDescriptor,
  RepoFile,
  RepoFileScanResult,
  RepoScanResult,
  ScannedFile,
} from "../types.js";
import { detectLanguage, isSourceLanguage } from "./language.js";
import {
  gitClone,
  gitFileCommitTimes,
  gitListFiles,
  gitMetadata,
} from "./git.js";
import {
  compareByPath,
  isProbablyBinary,
  knownHashFor,
  sha256File,
} from "./fileUtils.js";
import { IgnoreStack } from "./ignore.js";
import {
  clonePathForGitUrl,
  expandHome,
  isGitUrl,
  repoNameFromGitUrl,
} from "./paths.js";

export { filePayload, fileTreePayload } from "./payloads.js";

type DescribeOptions = {
  name?: string | undefined;
  source_type?: string | undefined;
};

type ScanOptions = DescribeOptions & {
  knownHashes?: Map<string, string>;
  knownFileMetadata?: Map<string, [number | null, string | null]>;
  hashPaths?: Set<string>;
};

export class RepoScanner {
  constructor(
    private readonly options: {
      maxFileSizeBytes?: number;
      storageDir?: string;
    } = {},
  ) {}

  describe(path: string, options: DescribeOptions = {}): RepoDescriptor {
    const requested = path.trim();
    let repoPath: string;
    let sourceType = options.source_type ?? "local";
    let defaultName: string;
    if (isGitUrl(requested)) {
      repoPath = this.ensureGitClone(requested);
      sourceType = "git";
      defaultName = repoNameFromGitUrl(requested);
    } else {
      repoPath = resolve(expandHome(requested));
      defaultName = basename(repoPath);
    }

    if (!existsSync(repoPath)) {
      throw new Error(`Repository path does not exist: ${repoPath}`);
    }
    if (!statSync(repoPath).isDirectory()) {
      throw new Error(`Repository path is not a directory: ${repoPath}`);
    }

    const metadata = gitMetadata(repoPath);
    return {
      id: createHash("sha1").update(repoPath).digest("hex").slice(0, 16),
      name: options.name ?? defaultName,
      path: repoPath,
      source_type: sourceType,
      git_url: metadata.git_url ?? (isGitUrl(requested) ? requested : null),
      commit_hash: metadata.commit_hash,
    };
  }

  scan(path: string, options: ScanOptions = {}): RepoScanResult {
    const repo = this.describe(path, options);
    const walk = this.walk(repo.path, { detectBinary: true });
    const files: ScannedFile[] = [];
    for (const absolutePath of walk.filePaths) {
      const stat = statSync(absolutePath);
      const metadata = this.fileMetadata(repo.path, absolutePath, stat);
      files.push({
        ...metadata,
        sha256:
          knownHashFor(
            metadata,
            options.knownHashes,
            options.knownFileMetadata,
            options.hashPaths,
          ) ?? sha256File(absolutePath),
      });
    }

    const commitTimes = gitFileCommitTimes(
      repo.path,
      files.filter((file) => file.is_source).map((file) => file.path),
    );
    return {
      repo,
      files: files
        .map((file) => ({
          ...file,
          last_commit_at: commitTimes.get(file.path) ?? null,
        }))
        .sort(compareByPath),
      scanned_count: files.length,
      ignored_count: walk.ignoredCount,
      skipped_count: walk.skippedCount,
    };
  }

  scanFiles(path: string, options: DescribeOptions = {}): RepoFileScanResult {
    const repo = this.describe(path, options);
    const gitFiles = gitListFiles(repo.path);
    let filePaths: string[];
    let ignoredCount = 0;
    let skippedCount = 0;

    if (gitFiles) {
      filePaths = [];
      for (const filePath of gitFiles) {
        const absolutePath = join(repo.path, filePath);
        try {
          const stat = statSync(absolutePath);
          if (!stat.isFile() || stat.size > this.maxFileSizeBytes) {
            skippedCount += 1;
            continue;
          }
          filePaths.push(absolutePath);
        } catch {
          skippedCount += 1;
        }
      }
    } else {
      const walk = this.walk(repo.path, { detectBinary: false });
      filePaths = walk.filePaths;
      ignoredCount = walk.ignoredCount;
      skippedCount = walk.skippedCount;
    }

    const files = filePaths
      .map((absolutePath) =>
        this.fileMetadata(repo.path, absolutePath, statSync(absolutePath)),
      )
      .sort(compareByPath);
    return {
      repo,
      files,
      scanned_count: files.length,
      ignored_count: ignoredCount,
      skipped_count: skippedCount,
    };
  }

  private get maxFileSizeBytes(): number {
    return this.options.maxFileSizeBytes ?? 2_000_000;
  }

  private get storageDir(): string {
    return resolve(this.options.storageDir ?? "./storage");
  }

  private ensureGitClone(gitUrl: string): string {
    const destination = clonePathForGitUrl(gitUrl, this.storageDir);
    if (existsSync(destination)) {
      const stat = statSync(destination);
      if (!stat.isDirectory()) {
        throw new Error(
          `Git clone destination is not a directory: ${destination}`,
        );
      }
      if (existsSync(join(destination, ".git"))) {
        return resolve(destination);
      }
      if (readdirSync(destination).length > 0) {
        throw new Error(
          `Git clone destination exists and is not a repository: ${destination}`,
        );
      }
    } else {
      mkdirSync(dirname(destination), { recursive: true });
    }
    return resolve(gitClone(gitUrl, destination));
  }

  private fileMetadata(
    root: string,
    absolutePath: string,
    stat: Stats,
  ): RepoFile {
    const path = relative(root, absolutePath).split("\\").join("/");
    const language = detectLanguage(path);
    return {
      path,
      absolute_path: absolutePath,
      language,
      is_source: isSourceLanguage(language),
      size_bytes: stat.size,
      modified_at: new Date(stat.mtimeMs).toISOString(),
    };
  }

  private walk(
    root: string,
    options: { detectBinary: boolean },
  ): {
    filePaths: string[];
    ignoredCount: number;
    skippedCount: number;
  } {
    const matcher = new IgnoreStack(root);
    const filePaths: string[] = [];
    let ignoredCount = 0;
    let skippedCount = 0;

    const visit = (directory: string): void => {
      matcher.addGitignore(directory);
      for (const entry of readdirSync(directory, { withFileTypes: true })) {
        const absolutePath = join(directory, entry.name);
        const relativePath = relative(root, absolutePath).split("\\").join("/");
        const isDirectory = entry.isDirectory();
        if (
          entry.isSymbolicLink() ||
          matcher.ignores(relativePath, isDirectory)
        ) {
          ignoredCount += 1;
          continue;
        }
        if (isDirectory) {
          visit(absolutePath);
          continue;
        }
        if (!entry.isFile()) {
          skippedCount += 1;
          continue;
        }
        const stat = lstatSync(absolutePath);
        if (stat.size > this.maxFileSizeBytes) {
          skippedCount += 1;
          continue;
        }
        if (options.detectBinary && isProbablyBinary(absolutePath)) {
          skippedCount += 1;
          continue;
        }
        filePaths.push(absolutePath);
      }
    };

    visit(root);
    return { filePaths, ignoredCount, skippedCount };
  }
}
