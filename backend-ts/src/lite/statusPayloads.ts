import type { LiteRepoContext } from "../lite.js";
import { countBy, repoPayload } from "./payloadCommon.js";

export function liteInitPayload(context: LiteRepoContext): {
  repo: ReturnType<typeof repoPayload>;
  database_path: string;
  lite_dir: string;
} {
  return {
    repo: repoPayload(context.repo),
    database_path: context.databasePath,
    lite_dir: context.liteDir,
  };
}

export function graphStatusPayload(context: LiteRepoContext): {
  repo_id: string;
  database_path: string;
  file_count: number;
  node_count: number;
  edge_count: number;
  chunk_count: number;
  community_count: number;
  nodes_by_type: Record<string, number>;
  edges_by_type: Record<string, number>;
  languages: Record<string, number>;
  pending_sync: boolean;
  pending_files: string[];
} {
  const graph = context.store.getGraph(context.repo.id);
  const liveScan = context.scanner.scanFiles(context.repo.path, {
    name: context.repo.name,
    source_type: context.repo.source_type,
  });
  const indexedFiles = new Set(
    graph.nodes
      .filter((node) => node.type === "file" || node.type === "config")
      .map((node) => node.file_path),
  );
  const pendingFiles = liveScan.files
    .filter((file) => !indexedFiles.has(file.path))
    .map((file) => file.path);
  return {
    repo_id: context.repo.id,
    database_path: context.databasePath,
    file_count: graph.nodes.filter(
      (node) => node.type === "file" || node.type === "config",
    ).length,
    node_count: graph.nodes.length,
    edge_count: graph.edges.length,
    chunk_count: context.store.listCodeChunks(context.repo.id).length,
    community_count: context.store.listGraphCommunities(context.repo.id).length,
    nodes_by_type: countBy(graph.nodes, (node) => node.type),
    edges_by_type: countBy(graph.edges, (edge) => edge.type),
    languages: countBy(
      graph.nodes.filter((node) => node.language),
      (node) => node.language ?? "",
    ),
    pending_sync: pendingFiles.length > 0,
    pending_files: pendingFiles,
  };
}
