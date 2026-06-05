import { initLiteRepo, syncLiteRepo, type LiteRepoContext } from "../lite.js";
import {
  affectedPayload,
  contextPayload,
  fileTree,
  graphImpactPayload,
  graphStatusPayload,
  indexedFilesPayload,
  liteInitPayload,
  liveFilesPayload,
  nodeContextPayload,
  nodePayload,
  relationshipPayload,
  tracePayload,
  type RelationshipDirection,
} from "./payloads.js";

export { formatFileTree as formatTree } from "../presenters/fileTree.js";
export type { FileTreeNode, RelationshipDirection } from "./payloads.js";

export type QueryFilters = {
  type?: string;
  language?: string;
  limit: number;
};

export type LiteFilesOptions = {
  sourceOnly?: boolean;
  live?: boolean;
};

export function liteInit(path: string, name?: string) {
  return withLiteRepo(path, name, liteInitPayload);
}

export function liteIndex(
  path: string,
  options: { name?: string; force?: boolean } = {},
) {
  return withLiteRepo(path, options.name, (context) => {
    const result = context.services.analysis.analyze(context.repo.id, {
      force: Boolean(options.force),
    });
    return {
      database_path: context.databasePath,
      run_id: result.run_id,
      repo_id: result.repo_id,
      status: result.status,
      mode: result.mode,
      scanned_count: result.scanned_count,
      parsed_file_count: result.parsed_file_count,
      reused_file_count: result.reused_file_count,
      node_count: result.node_count,
      edge_count: result.edge_count,
      chunk_count: result.chunk_count,
      community_count: result.community_count,
      community_count_by_level: result.community_count_by_level,
      errors: result.errors,
    };
  });
}

export function liteSync(path: string) {
  return withLiteRepo(path, undefined, (context) => {
    const result = syncLiteRepo(context);
    return {
      database_path: context.databasePath,
      run_id: result.run_id,
      repo_id: result.repo_id,
      status: result.status,
      mode: result.mode,
      scanned_count: result.scanned_count,
      node_count: result.node_count,
      edge_count: result.edge_count,
      chunk_count: result.chunk_count,
      community_count: result.community_count,
    };
  });
}

export function liteStatus(path: string) {
  return withLiteRepo(path, undefined, graphStatusPayload);
}

export function liteQuery(path: string, search: string, filters: QueryFilters) {
  return withLiteRepo(path, undefined, (context) => {
    const searchFilters: {
      types?: string[];
      languages?: string[];
      limit: number;
    } = { limit: filters.limit };
    if (filters.type) {
      searchFilters.types = [filters.type];
    }
    if (filters.language) {
      searchFilters.languages = [filters.language];
    }
    const results = context.store
      .searchCodeNodes(context.repo.id, search, searchFilters)
      .map((hit) => ({
        node: nodePayload(hit.node),
        score: hit.score,
        reasons: hit.reasons,
      }));
    return { repo_id: context.repo.id, query: search, results };
  });
}

export function liteRelationships(
  path: string,
  symbol: string,
  direction: RelationshipDirection,
  limit: number,
) {
  return withLiteRepo(path, undefined, (context) =>
    relationshipPayload(context, symbol, direction, limit),
  );
}

export function liteImpact(path: string, symbol: string, depth: number) {
  return withLiteRepo(path, undefined, (context) =>
    graphImpactPayload(context, symbol, depth),
  );
}

export function liteContext(
  path: string,
  task: string,
  maxFiles: number,
  maxNodes: number,
) {
  return withLiteRepo(path, undefined, (context) =>
    contextPayload(context, task, maxFiles, maxNodes),
  );
}

export function liteTrace(
  path: string,
  fromSymbol: string,
  toSymbol: string,
  maxDepth: number,
) {
  return withLiteRepo(path, undefined, (context) =>
    tracePayload(context, fromSymbol, toSymbol, maxDepth),
  );
}

export function liteNode(path: string, symbol: string, includeCode: boolean) {
  return withLiteRepo(path, undefined, (context) =>
    nodeContextPayload(context, symbol, includeCode),
  );
}

export function liteFiles(path: string, options: LiteFilesOptions = {}) {
  return withLiteRepo(path, undefined, (context) => {
    const payload = options.live
      ? liveFilesPayload(context)
      : indexedFilesPayload(context);
    if (!options.sourceOnly) {
      return payload;
    }
    const files = payload.files.filter((file) => file.is_source);
    return {
      ...payload,
      files,
      root: fileTree(payload.repo_name, files),
    };
  });
}

export function liteAffected(
  path: string,
  changedFiles: string[],
  depth: number,
  testGlob?: string,
) {
  return withLiteRepo(path, undefined, (context) =>
    affectedPayload(context, changedFiles, depth, testGlob),
  );
}

function withLiteRepo<T>(
  path: string,
  name: string | undefined,
  fn: (context: LiteRepoContext) => T,
): T {
  const context = initLiteRepo(name ? { path, name } : { path });
  try {
    return fn(context);
  } finally {
    context.store.close();
  }
}
