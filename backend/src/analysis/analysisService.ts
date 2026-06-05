import type { CodeWikiStoreApi } from "../db/types.js";
import { notFoundError } from "../errors.js";
import { RepoScanner } from "../scanner/scanner.js";
import type {
  AnalysisResult,
  CodeGraphNode,
  IncrementalUpdatePlan,
  JsonObject,
  RepoDescriptor,
  RepoScanResult,
  RepositoryUpdateResult,
} from "../types.js";
import { buildRepositoryGraph } from "./repositoryGraphBuilder.js";

export class AnalysisService {
  constructor(
    private readonly store: CodeWikiStoreApi,
    private readonly scanner: RepoScanner,
  ) {}

  analyze(repoId: string, options: { force?: boolean; runId?: string } = {}) {
    const repo = this.repo(repoId);
    const scan = this.scanRepo(repo);
    return this.persistAnalysis(repoId, scan, {
      mode: "typescript",
      runId: options.runId,
      reusedFileCount: 0,
      statsExtra: {},
    });
  }

  planUpdate(repoId: string): IncrementalUpdatePlan {
    const repo = this.repo(repoId);
    return this.planFromScan(repoId, this.scanRepo(repo), repo);
  }

  update(repoId: string): RepositoryUpdateResult {
    const repo = this.repo(repoId);
    const scan = this.scanRepo(repo);
    const plan = this.planFromScan(repoId, scan, repo);
    const existingGraph = this.store.getGraph(repoId);
    if (!plan.affected_files.length && existingGraph.nodes.length) {
      const chunks = this.store.listCodeChunks(repoId);
      const communities = this.store.listGraphCommunities(repoId);
      const run = this.store.createAnalysisRun(repoId);
      const stats = {
        mode: "typescript_update",
        plan,
        scanned_count: scan.scanned_count,
        parsed_file_count: 0,
        reused_file_count: plan.unchanged_files.length,
        node_count: existingGraph.nodes.length,
        edge_count: existingGraph.edges.length,
        chunk_count: chunks.length,
        community_count: communities.length,
        community_count_by_level: communityCountByLevel(communities),
        stale_pages: [],
        errors: [],
        progress: {
          stage: "done",
          label: "Done",
          message: "Repository update complete: no file changes detected.",
        },
      } satisfies JsonObject;
      const finished = this.store.finishAnalysisRun(run.id, {
        status: "done",
        stats,
      });
      return {
        run_id: finished.id,
        repo_id: repoId,
        status: finished.status,
        scanned_count: scan.scanned_count,
        parsed_file_count: 0,
        reused_file_count: plan.unchanged_files.length,
        node_count: existingGraph.nodes.length,
        edge_count: existingGraph.edges.length,
        chunk_count: chunks.length,
        community_count: communities.length,
        community_count_by_level: communityCountByLevel(communities),
        errors: [],
        mode: "typescript_update",
        plan,
        stale_pages: [],
      };
    }

    return {
      ...this.persistAnalysis(repoId, scan, {
        mode: "typescript_update",
        reusedFileCount: 0,
        statsExtra: {
          plan,
          stale_pages: stalePagesForFiles(
            this.store,
            repoId,
            plan.affected_files,
          ),
        },
      }),
      plan,
      stale_pages: stalePagesForFiles(this.store, repoId, plan.affected_files),
    };
  }

  private repo(repoId: string): RepoDescriptor {
    const repo = this.store.getRepo(repoId);
    if (!repo) {
      throw notFoundError("Repository", repoId);
    }
    return repo;
  }

  private scanRepo(repo: RepoDescriptor): RepoScanResult {
    return this.scanner.scan(repo.path, {
      name: repo.name,
      source_type: repo.source_type,
    });
  }

  private persistAnalysis(
    repoId: string,
    scan: RepoScanResult,
    options: {
      mode: string;
      runId?: string | undefined;
      reusedFileCount: number;
      statsExtra: JsonObject;
    },
  ): AnalysisResult {
    const run = options.runId
      ? this.store.getAnalysisRun(options.runId)
      : this.store.createAnalysisRun(repoId);
    if (!run || run.repo_id !== repoId) {
      throw notFoundError("Analysis run", options.runId ?? "new run");
    }

    try {
      const { nodes, edges, chunks, communities } = buildRepositoryGraph(
        repoId,
        scan.files,
      );
      this.store.replaceGraph(repoId, { nodes, edges, chunks });
      this.store.replaceGraphCommunities(repoId, communities);
      this.store.replaceGraphCommunityEdges(repoId, []);
      this.store.upsertRepo(scan.repo);

      const parsedFileCount = scan.files.filter(
        (file) => file.is_source,
      ).length;
      const stats = {
        mode: options.mode,
        scanned_count: scan.scanned_count,
        parsed_file_count: parsedFileCount,
        reused_file_count: options.reusedFileCount,
        node_count: nodes.length,
        edge_count: edges.length,
        chunk_count: chunks.length,
        community_count: communities.length,
        community_count_by_level: { "0": communities.length },
        errors: [],
        progress: {
          stage: "done",
          label: "Done",
          message: `Analysis complete: ${nodes.length} nodes, ${edges.length} edges.`,
        },
        ...options.statsExtra,
      } satisfies JsonObject;
      const finished = this.store.finishAnalysisRun(run.id, {
        status: "done",
        stats,
      });
      return {
        run_id: finished.id,
        repo_id: repoId,
        status: finished.status,
        scanned_count: scan.scanned_count,
        parsed_file_count: parsedFileCount,
        reused_file_count: options.reusedFileCount,
        node_count: nodes.length,
        edge_count: edges.length,
        chunk_count: chunks.length,
        community_count: communities.length,
        community_count_by_level: { "0": communities.length },
        errors: [],
        mode: options.mode,
      };
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      this.store.finishAnalysisRun(run.id, {
        status: "failed",
        stats: {
          mode: options.mode,
          errors: [{ message }],
          progress: { stage: "failed", label: "Failed", message },
          ...options.statsExtra,
        },
        error: message,
      });
      throw error;
    }
  }

  private planFromScan(
    repoId: string,
    scan: RepoScanResult,
    previousRepo: RepoDescriptor,
  ): IncrementalUpdatePlan {
    const currentFileHashes = currentFileHashesByPath(
      this.store.getGraph(repoId).nodes,
    );
    const scannedFileHashes = new Map(
      scan.files.map((file) => [file.path, file.sha256]),
    );
    const changedFiles = [...scannedFileHashes]
      .filter(
        ([path, hash]) =>
          currentFileHashes.has(path) && currentFileHashes.get(path) !== hash,
      )
      .map(([path]) => path)
      .sort();
    const newFiles = [...scannedFileHashes.keys()]
      .filter((path) => !currentFileHashes.has(path))
      .sort();
    const deletedFiles = [...currentFileHashes.keys()]
      .filter((path) => !scannedFileHashes.has(path))
      .sort();
    const unchangedFiles = [...scannedFileHashes]
      .filter(([path, hash]) => currentFileHashes.get(path) === hash)
      .map(([path]) => path)
      .sort();
    const affectedFiles = uniqueSorted([
      ...changedFiles,
      ...newFiles,
      ...deletedFiles,
    ]);
    return {
      repo_id: repoId,
      changed_files: changedFiles,
      new_files: newFiles,
      deleted_files: deletedFiles,
      unchanged_files: unchangedFiles,
      affected_files: affectedFiles,
      detection_strategy: "sha256",
      base_commit: previousRepo.commit_hash,
      head_commit: scan.repo.commit_hash,
    };
  }
}

export { buildRepositoryGraph } from "./repositoryGraphBuilder.js";

export function analysisRunResponse(store: CodeWikiStoreApi, runId: string) {
  const run = store.getAnalysisRun(runId);
  if (!run) {
    throw notFoundError("Analysis run", runId);
  }
  const stats = run.stats;
  return {
    run_id: run.id,
    id: run.id,
    repo_id: run.repo_id,
    status: run.status,
    started_at: run.started_at,
    finished_at: run.finished_at,
    error: run.error,
    stats,
    mode: stringStat(stats.mode),
    scanned_count: numberStat(stats.scanned_count),
    parsed_file_count: numberStat(stats.parsed_file_count),
    reused_file_count: numberStat(stats.reused_file_count),
    node_count: numberStat(stats.node_count),
    edge_count: numberStat(stats.edge_count),
    chunk_count: numberStat(stats.chunk_count),
    community_count: numberStat(stats.community_count),
    community_count_by_level:
      typeof stats.community_count_by_level === "object" &&
      stats.community_count_by_level !== null
        ? stats.community_count_by_level
        : {},
    errors: Array.isArray(stats.errors) ? stats.errors : [],
  };
}

function numberStat(value: unknown): number {
  return typeof value === "number" ? value : 0;
}

function stringStat(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function currentFileHashesByPath(nodes: CodeGraphNode[]): Map<string, string> {
  return new Map(
    nodes
      .filter(
        (node) =>
          (node.type === "file" || node.type === "config") &&
          node.file_path &&
          node.hash,
      )
      .map((node) => [node.file_path, node.hash]),
  );
}

function uniqueSorted(values: string[]): string[] {
  return [...new Set(values)].sort((left, right) => left.localeCompare(right));
}

function stalePagesForFiles(
  store: CodeWikiStoreApi,
  repoId: string,
  filePaths: string[],
): string[] {
  const affected = new Set(filePaths);
  if (!affected.size) {
    return [];
  }
  return store
    .listDocPages(repoId)
    .filter((page) =>
      page.source_refs.some(
        (ref) =>
          typeof ref.file_path === "string" && affected.has(ref.file_path),
      ),
    )
    .map((page) => page.slug)
    .sort();
}

function communityCountByLevel(
  communities: Array<{ level: number }>,
): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const community of communities) {
    const key = String(community.level);
    counts[key] = (counts[key] ?? 0) + 1;
  }
  return counts;
}
