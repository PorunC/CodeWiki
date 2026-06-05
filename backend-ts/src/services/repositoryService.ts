import type { CodeWikiStore } from "../db/store.js";
import { notFoundError } from "../errors.js";
import type { RepoScanner } from "../scanner/scanner.js";
import type {
  RepoDescriptor,
  RepoFileScanResult,
  RepoScanResult,
} from "../types.js";
import {
  ensureRepo,
  resolveRegisteredRepo,
  resolveRepo,
  selectedRepo,
  type RepoResolveOptions,
} from "./repoResolver.js";

export type RepositoryInputOptions = {
  name?: string | undefined;
  sourceType?: string | undefined;
};

export type RepositoryFilesResult = {
  repo: RepoDescriptor;
  scan: RepoFileScanResult;
};

export type RepositoryDeleteResult = {
  repo: RepoDescriptor;
  deleted: boolean;
};

export class RepositoryService {
  constructor(
    private readonly store: CodeWikiStore,
    private readonly scanner: RepoScanner,
  ) {}

  register(path: string, options: RepositoryInputOptions = {}): RepoDescriptor {
    return this.store.upsertRepo(
      this.scanner.describe(path, scannerOptions(options)),
    );
  }

  scan(path: string, options: RepositoryInputOptions = {}): RepoScanResult {
    return this.scanner.scan(path, scannerOptions(options));
  }

  list(): RepoDescriptor[] {
    return this.store.listRepos();
  }

  get(repoId: string): RepoDescriptor {
    const repo = this.store.getRepo(repoId);
    if (!repo) {
      throw notFoundError("Repository", repoId);
    }
    return repo;
  }

  delete(repoId: string): boolean {
    if (!this.store.deleteRepo(repoId)) {
      throw notFoundError("Repository", repoId);
    }
    return true;
  }

  deleteBySelector(selector: string): RepositoryDeleteResult {
    const repo = this.resolveRegistered(selector);
    return { repo, deleted: this.delete(repo.id) };
  }

  resolveRegistered(selector: string): RepoDescriptor {
    return resolveRegisteredRepo(this.store, selector);
  }

  selected(selector: string | undefined): RepoDescriptor {
    return selectedRepo(this.store, selector);
  }

  resolve(
    selector: string | null | undefined,
    options: RepoResolveOptions = {},
  ): RepoDescriptor {
    return resolveRepo(this.store, this.scanner, selector, options);
  }

  ensure(selector: string): RepoDescriptor {
    return ensureRepo(this.store, this.scanner, selector);
  }

  filesForRepo(repo: RepoDescriptor): RepoFileScanResult {
    return this.scanner.scanFiles(repo.path, {
      name: repo.name,
      source_type: repo.source_type,
    });
  }

  filesForId(repoId: string): RepositoryFilesResult {
    const repo = this.get(repoId);
    return { repo, scan: this.filesForRepo(repo) };
  }

  filesForSelector(selector: string | undefined): RepositoryFilesResult {
    const repo = this.selected(selector);
    return { repo, scan: this.filesForRepo(repo) };
  }
}

function scannerOptions(options: RepositoryInputOptions): {
  name?: string | undefined;
  source_type?: string | undefined;
} {
  return {
    name: options.name,
    source_type: options.sourceType ?? "local",
  };
}
