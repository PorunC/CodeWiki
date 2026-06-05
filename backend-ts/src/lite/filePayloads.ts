import type { LiteRepoContext } from "../lite.js";
import {
  fileRecordFromNode,
  fileTree,
  isLikelyTestFile,
  type FileRecord,
} from "./payloadCommon.js";

export function liveFilesPayload(context: LiteRepoContext): {
  repo_id: string;
  repo_name: string;
  root: ReturnType<typeof fileTree>;
  files: FileRecord[];
  scanned_count: number;
  ignored_count: number;
  skipped_count: number;
  source: "live";
} {
  const scan = context.scanner.scan(context.repo.path, {
    name: context.repo.name,
    source_type: context.repo.source_type,
  });
  const files = scan.files.map((file) => ({
    path: file.path,
    absolute_path: file.absolute_path,
    language: file.language,
    is_source: file.is_source,
    size_bytes: file.size_bytes,
    sha256: file.sha256,
    modified_at: file.modified_at,
    type: file.is_source ? "file" : "config",
  }));
  return {
    repo_id: context.repo.id,
    repo_name: context.repo.name,
    root: fileTree(context.repo.name, files),
    files,
    scanned_count: scan.scanned_count,
    ignored_count: scan.ignored_count,
    skipped_count: scan.skipped_count,
    source: "live",
  };
}

export function indexedFilesPayload(context: LiteRepoContext): {
  repo_id: string;
  repo_name: string;
  root: ReturnType<typeof fileTree>;
  files: FileRecord[];
  scanned_count: number;
  ignored_count: number;
  skipped_count: number;
  source: "index";
} {
  const files = context.store
    .getGraph(context.repo.id)
    .nodes.filter((node) => node.type === "file" || node.type === "config")
    .sort((left, right) => left.file_path.localeCompare(right.file_path))
    .map(fileRecordFromNode);
  return {
    repo_id: context.repo.id,
    repo_name: context.repo.name,
    root: fileTree(context.repo.name, files),
    files,
    scanned_count: files.length,
    ignored_count: 0,
    skipped_count: 0,
    source: "index",
  };
}

export function affectedPayload(
  context: LiteRepoContext,
  changedFiles: string[],
  depth: number,
  testGlob: string | undefined,
): {
  repo_id: string;
  changed_files: string[];
  affected_files: string[];
  affected_tests: string[];
  affected_wiki_pages: string[];
  affected_node_ids: string[];
  traversed_file_count: number;
  depth: number;
  test_glob: string | null;
} {
  const graph = context.store.getGraph(context.repo.id);
  const changed = new Set(changedFiles.map((file) => file.replace(/\\/g, "/")));
  const affectedNodeIds = new Set(
    graph.nodes
      .filter((node) => changed.has(node.file_path))
      .map((node) => node.id),
  );
  let frontier = new Set(affectedNodeIds);
  for (let level = 0; level < depth && frontier.size; level += 1) {
    const next = new Set<string>();
    for (const edge of graph.edges) {
      if (!frontier.has(edge.source_id) && !frontier.has(edge.target_id)) {
        continue;
      }
      for (const nodeId of [edge.source_id, edge.target_id]) {
        if (!affectedNodeIds.has(nodeId)) {
          affectedNodeIds.add(nodeId);
          next.add(nodeId);
        }
      }
    }
    frontier = next;
  }
  const affectedFiles = new Set(changed);
  const affectedTests = new Set<string>();
  for (const node of graph.nodes.filter((candidate) =>
    affectedNodeIds.has(candidate.id),
  )) {
    if (node.file_path) {
      affectedFiles.add(node.file_path);
      if (isLikelyTestFile(node.file_path, testGlob)) {
        affectedTests.add(node.file_path);
      }
    }
  }
  return {
    repo_id: context.repo.id,
    changed_files: [...changed],
    affected_files: [...affectedFiles].sort(),
    affected_tests: [...affectedTests].sort(),
    affected_wiki_pages: [],
    affected_node_ids: [...affectedNodeIds],
    traversed_file_count: affectedFiles.size,
    depth,
    test_glob: testGlob ?? null,
  };
}
