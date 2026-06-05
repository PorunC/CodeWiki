import { dirname } from "node:path";
import type { CodeGraphNode, GraphCommunity } from "../types.js";
import { digest, pushMap } from "./graphUtils.js";

export function buildCommunities(
  repoId: string,
  nodes: CodeGraphNode[],
): GraphCommunity[] {
  const byDirectory = new Map<string, string[]>();
  for (const node of nodes) {
    if (node.type !== "file" && node.type !== "config") {
      continue;
    }
    const directory = dirname(node.file_path);
    pushMap(byDirectory, directory === "." ? "root" : directory, node.id);
  }
  return [...byDirectory.entries()]
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([name, nodeIds], index) => ({
      id: digest(`${repoId}:community:${name}`),
      repo_id: repoId,
      name,
      level: 0,
      parent_id: null,
      rank: index,
      node_ids: nodeIds,
      summary: `Files under ${name}.`,
      summary_hash: digest(`${name}:${nodeIds.join(",")}`),
      created_at: new Date().toISOString(),
    }));
}
