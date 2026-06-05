import type { CodeWikiStoreApi } from "../db/types.js";
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
    private readonly store: CodeWikiStoreApi,
    private readonly scanner: RepoScanner,
  ) {}

  async register(
    path: string,
    options: RepositoryInputOptions = {},
  ): Promise<RepoDescriptor> {
    return this.store.upsertRepo(
      this.scanner.describe(path, scannerOptions(options)),
    );
  }

  scan(path: string, options: RepositoryInputOptions = {}): RepoScanResult {
    return this.scanner.scan(path, scannerOptions(options));
  }

  async list(): Promise<RepoDescriptor[]> {
    return this.store.listRepos();
  }

  async get(repoId: string): Promise<RepoDescriptor> {
    const repo = await this.store.getRepo(repoId);
    if (!repo) {
      throw notFoundError("Repository", repoId);
    }
    return repo;
  }

  async delete(repoId: string): Promise<boolean> {
    if (!(await this.store.deleteRepo(repoId))) {
      throw notFoundError("Repository", repoId);
    }
    return true;
  }

  async deleteBySelector(selector: string): Promise<RepositoryDeleteResult> {
    const repo = await this.resolveRegistered(selector);
    return { repo, deleted: await this.delete(repo.id) };
  }

  async resolveRegistered(selector: string): Promise<RepoDescriptor> {
    return resolveRegisteredRepo(this.store, selector);
  }

  async selected(selector: string | undefined): Promise<RepoDescriptor> {
    return selectedRepo(this.store, selector);
  }

  resolve(
    selector: string | null | undefined,
    options: RepoResolveOptions = {},
  ): Promise<RepoDescriptor> {
    return resolveRepo(this.store, this.scanner, selector, options);
  }

  async ensure(selector: string): Promise<RepoDescriptor> {
    return ensureRepo(this.store, this.scanner, selector);
  }

  filesForRepo(repo: RepoDescriptor): RepoFileScanResult {
    return this.scanner.scanFiles(repo.path, {
      name: repo.name,
      source_type: repo.source_type,
    });
  }

  async filesForId(repoId: string): Promise<RepositoryFilesResult> {
    const repo = await this.get(repoId);
    return { repo, scan: this.filesForRepo(repo) };
  }

  async filesForSelector(
    selector: string | undefined,
  ): Promise<RepositoryFilesResult> {
    const repo = await this.selected(selector);
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
