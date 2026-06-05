import type { CodeWikiStore } from "../db/store.js";
import { notFoundError } from "../errors.js";
import type {
  CodeGraphEdge,
  CodeGraphNode,
  GraphCommunity,
  GraphCommunityEdge,
} from "../types.js";
import { digest } from "../analysis/graphUtils.js";
import {
  FALLBACK_COMMUNITY_NAME,
  GENERIC_FILE_LABELS,
  dedupeName,
  fileLabel,
  humanizeName,
  isGenericName,
  lastPathPart,
} from "./communityNamingRules.js";

export type CommunityNamingResult = {
  repo_id: string;
  status: "renamed" | "unchanged" | "no_communities";
  renamed_count: number;
  community_count: number;
  max_communities: number;
  named_community_ids: string[];
  errors: string[];
};

type CommunityProfile = {
  files: string[];
  symbols: Array<{ name: string; type: string; filePath: string }>;
  edgeTypes: string[];
};

const DEFAULT_MAX_COMMUNITIES = 40;
export function nameGraphCommunities(
  store: CodeWikiStore,
  repoId: string,
  options: { maxCommunities?: number } = {},
): CommunityNamingResult {
  if (!store.getRepo(repoId)) {
    throw notFoundError("Repository", repoId);
  }

  const communities = store.listGraphCommunities(repoId);
  const maxCommunities = normalizeMaxCommunities(options.maxCommunities);
  if (!communities.length) {
    return {
      repo_id: repoId,
      status: "no_communities",
      renamed_count: 0,
      community_count: 0,
      max_communities: maxCommunities,
      named_community_ids: [],
      errors: [],
    };
  }

  const graph = store.getGraph(repoId);
  const communityEdges = store.listGraphCommunityEdges(repoId);
  const targets = selectNamingTargets(communities, maxCommunities);
  const targetIds = new Set(targets.map((community) => community.id));
  const seenNames = new Set(
    communities
      .filter((community) => !targetIds.has(community.id))
      .map((community) => community.name.toLowerCase()),
  );

  const renamed = communities.map((community, index) => {
    if (!targetIds.has(community.id)) {
      return community;
    }
    const profile = communityProfile(community, graph.nodes, graph.edges);
    const preferredName = nameFromProfile(community, profile, index);
    const name = dedupeName(preferredName, seenNames);
    seenNames.add(name.toLowerCase());
    const summary = summaryFromProfile(name, community, profile);
    return {
      ...community,
      name,
      summary,
      summary_hash: digest(summary),
    };
  });

  store.replaceGraphCommunities(repoId, renamed);
  preserveCommunityEdges(store, repoId, renamed, communityEdges);

  const renamedCount = renamedCountBetween(communities, renamed);
  return {
    repo_id: repoId,
    status: renamedCount > 0 ? "renamed" : "unchanged",
    renamed_count: renamedCount,
    community_count: communities.length,
    max_communities: maxCommunities,
    named_community_ids: targets.map((community) => community.id),
    errors: [],
  };
}

function normalizeMaxCommunities(value: number | undefined): number {
  if (!Number.isInteger(value) || value === undefined) {
    return DEFAULT_MAX_COMMUNITIES;
  }
  return Math.max(1, Math.min(value, DEFAULT_MAX_COMMUNITIES));
}

function selectNamingTargets(
  communities: GraphCommunity[],
  maxCommunities: number,
): GraphCommunity[] {
  return [...communities]
    .sort(
      (left, right) =>
        left.level - right.level ||
        left.rank - right.rank ||
        right.node_ids.length - left.node_ids.length ||
        left.name.localeCompare(right.name),
    )
    .slice(0, maxCommunities);
}

function communityProfile(
  community: GraphCommunity,
  nodes: CodeGraphNode[],
  edges: CodeGraphEdge[],
): CommunityProfile {
  const directNodeIds = new Set(community.node_ids);
  const directNodes = community.node_ids
    .map((nodeId) => nodes.find((node) => node.id === nodeId))
    .filter((node): node is CodeGraphNode => Boolean(node));
  const files = uniqueSorted(
    directNodes
      .map((node) => node.file_path)
      .filter((filePath) => filePath.length > 0),
  );
  const fileSet = new Set(files);
  const symbols = nodes
    .filter(
      (node) =>
        node.type !== "file" &&
        node.type !== "config" &&
        (directNodeIds.has(node.id) || fileSet.has(node.file_path)),
    )
    .sort(
      (left, right) =>
        left.file_path.localeCompare(right.file_path) ||
        (left.start_line ?? 0) - (right.start_line ?? 0) ||
        left.name.localeCompare(right.name),
    )
    .slice(0, 8)
    .map((node) => ({
      name: node.name,
      type: node.type,
      filePath: node.file_path,
    }));
  const edgeTypes = uniqueSorted(
    edges
      .filter(
        (edge) =>
          directNodeIds.has(edge.source_id) ||
          directNodeIds.has(edge.target_id),
      )
      .map((edge) => edge.type),
  );
  return { files, symbols, edgeTypes };
}

function nameFromProfile(
  community: GraphCommunity,
  profile: CommunityProfile,
  index: number,
): string {
  const labels = uniquePreserveOrder(
    profile.files
      .map(fileLabel)
      .filter((label) => !GENERIC_FILE_LABELS.has(label.toLowerCase())),
  );
  if (labels.length === 1 && labels[0]) {
    return labels[0];
  }
  if (labels.length > 1 && labels[0] && labels[1]) {
    return `${labels[0]} and ${labels[1]}`;
  }
  const symbol = profile.symbols.find((candidate) => candidate.name);
  if (symbol) {
    return humanizeName(symbol.name);
  }
  const directoryName = lastPathPart(community.name);
  const fallback = humanizeName(directoryName);
  return isGenericName(fallback)
    ? `${FALLBACK_COMMUNITY_NAME} ${index + 1}`
    : fallback;
}

function summaryFromProfile(
  name: string,
  community: GraphCommunity,
  profile: CommunityProfile,
): string {
  const files = profile.files.slice(0, 4);
  const fileText = files.length
    ? files.map((file) => `\`${file}\``).join(", ")
    : "the indexed repository files";
  const symbolText = profile.symbols.length
    ? ` Key symbols include ${profile.symbols
        .slice(0, 4)
        .map((symbol) => `\`${symbol.name}\` (${symbol.type})`)
        .join(", ")}.`
    : "";
  const edgeText = profile.edgeTypes.length
    ? ` Relationships include ${profile.edgeTypes.slice(0, 3).join(", ")}.`
    : "";
  return `${name} covers ${fileText} for graph community ${community.rank + 1}.${symbolText}${edgeText}`;
}

function preserveCommunityEdges(
  store: CodeWikiStore,
  repoId: string,
  communities: GraphCommunity[],
  edges: GraphCommunityEdge[],
): void {
  if (!edges.length) {
    return;
  }
  const communityIds = new Set(communities.map((community) => community.id));
  store.replaceGraphCommunityEdges(
    repoId,
    edges.filter(
      (edge) =>
        communityIds.has(edge.source_community_id) &&
        communityIds.has(edge.target_community_id),
    ),
  );
}

function renamedCountBetween(
  before: GraphCommunity[],
  after: GraphCommunity[],
): number {
  const beforeById = new Map(
    before.map((community) => [community.id, community]),
  );
  return after.filter((community) => {
    const previous = beforeById.get(community.id);
    return (
      previous !== undefined &&
      (previous.name !== community.name ||
        previous.summary !== community.summary)
    );
  }).length;
}

function uniqueSorted(values: string[]): string[] {
  return [...new Set(values)].sort((left, right) => left.localeCompare(right));
}

function uniquePreserveOrder(values: string[]): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const value of values) {
    const key = value.toLowerCase();
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    result.push(value);
  }
  return result;
}
