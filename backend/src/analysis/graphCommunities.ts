import { createRequire } from "node:module";
import { UndirectedGraph } from "graphology";
import type {
  CodeGraphEdge,
  CodeGraphNode,
  GraphCommunity,
  GraphCommunityEdge,
} from "../types.js";
import { digest } from "./graphUtils.js";

const COMMUNITY_NODE_TYPES = new Set([
  "file",
  "config",
  "class",
  "function",
  "method",
  "schema",
  "endpoint",
]);
const COMMUNITY_EDGE_WEIGHTS: Record<string, number> = {
  calls: 1,
  routes_to: 1,
  inherits: 0.9,
  implements: 0.86,
  imports: 0.75,
  exports: 0.65,
  references: 0.62,
  uses_config: 0.58,
  defines: 0.5,
  contains: 0.42,
};
const LEAF_RESOLUTION = 2;
const DETAIL_RESOLUTION = 3;
const PARENT_RESOLUTION = 0.5;
const LOUVAIN_RANDOM_SEED = 42;
const MAX_COMMUNITIES = 32;
const MAX_PARENT_COMMUNITIES = 24;
const MAX_CHILD_COMMUNITIES_PER_PARENT = 12;
const MIN_CHILD_NODES = 8;
const MIN_PARENT_NODES = 24;
const DETAIL_SPLIT_NODE_THRESHOLD = 120;
const DETAIL_SPLIT_FILE_THRESHOLD = 32;
const MIN_DETAIL_NODES = 12;
const MAX_DETAIL_COMMUNITIES_PER_CHILD = 8;
const MAX_TOTAL_COMMUNITIES = 128;
const MIN_COMMUNITY_EDGE_WEIGHT = 0.01;
const MAX_EVIDENCE_EDGE_IDS = 24;
const COMMUNITY_DEPENDENCY_EDGE_TYPES: Record<string, string> = {
  calls: "calls_into",
  imports: "imports_from",
  exports: "imports_from",
  routes_to: "routes_to",
};
const IGNORED_AGGREGATE_EDGE_TYPES = new Set(["contains", "defines"]);

type DetectedCommunity = {
  key: string;
  nodeIds: string[];
  level: number;
  parentKey: string | null;
  rank: number;
};

type CommunityRecord = GraphCommunity & {
  fileCount: number;
};

type EdgeAggregate = {
  weight: number;
  confidenceTotal: number;
  count: number;
  evidenceEdgeIds: string[];
  sourceTypes: Map<string, number>;
};

type WeightedGraph = {
  nodes: Set<string>;
  adjacency: Map<string, Map<string, number>>;
};

type WeightedEdgeAttributes = {
  weight: number;
};

type CommunityLouvainRunner = (
  graph: UndirectedGraph<Record<string, never>, WeightedEdgeAttributes>,
  options: {
    getEdgeWeight: "weight";
    randomWalk: boolean;
    resolution: number;
    rng: () => number;
  },
) => Record<string, number>;

const require = createRequire(import.meta.url);
const runLouvain =
  require("graphology-communities-louvain") as CommunityLouvainRunner;

export function buildCommunities(
  repoId: string,
  nodes: CodeGraphNode[],
): GraphCommunity[] {
  const { communities } = buildCommunityGraph(repoId, nodes, []);
  return communities;
}

export function buildCommunityGraph(
  repoId: string,
  nodes: CodeGraphNode[],
  edges: CodeGraphEdge[],
): { communities: GraphCommunity[]; communityEdges: GraphCommunityEdge[] } {
  const eligibleNodes = nodes.filter(isCommunityNode);
  const nodeById = new Map(eligibleNodes.map((node) => [node.id, node]));
  const detected = detectCommunities(eligibleNodes, edges, nodeById);

  const now = new Date().toISOString();
  const communityByKey = new Map<string, CommunityRecord>();
  const communityRecords: CommunityRecord[] = detected.map((community) => {
    const parentId = community.parentKey
      ? (communityByKey.get(community.parentKey)?.id ?? null)
      : null;
    const record = communityRecord(repoId, community, {
      parentId,
      nodeById,
      createdAt: now,
    });
    communityByKey.set(community.key, record);
    return record;
  });

  const communities = communityRecords.map(stripCommunityRecord);
  return {
    communities,
    communityEdges: buildCommunityEdges(repoId, communities, edges),
  };
}

function detectCommunities(
  nodes: CodeGraphNode[],
  edges: CodeGraphEdge[],
  nodeById: Map<string, CodeGraphNode>,
): DetectedCommunity[] {
  const graph = buildWeightedGraph(nodes, edges);
  const leafCommunities = partitionWeightedGraph(graph, LEAF_RESOLUTION);
  let leafPartitions = rankPartitions(leafCommunities, nodeById);
  if (leafPartitions.length <= 1) {
    return leafPartitions.slice(0, MAX_COMMUNITIES).map((nodeIds, rank) => ({
      key: communityKey(nodeIds),
      nodeIds,
      level: 0,
      parentKey: null,
      rank,
    }));
  }

  const initialCommunityGraph = buildPartitionGraph(graph, leafPartitions);
  leafPartitions = mergeSmallLeafPartitions(
    leafPartitions,
    initialCommunityGraph,
  );
  const communityGraph = buildPartitionGraph(graph, leafPartitions);
  const parentPartitions = normalizeParentPartitions(
    rankNumberPartitions(
      partitionWeightedNumberGraph(communityGraph, PARENT_RESOLUTION),
      leafPartitions,
    ),
    leafPartitions,
    communityGraph,
  );
  return detectedHierarchy(parentPartitions, leafPartitions, nodeById, graph);
}

function buildWeightedGraph(
  nodes: CodeGraphNode[],
  edges: CodeGraphEdge[],
): WeightedGraph {
  const nodeIds = new Set(nodes.map((node) => node.id));
  const adjacency = new Map<string, Map<string, number>>();
  for (const nodeId of nodeIds) {
    adjacency.set(nodeId, new Map());
  }
  for (const edge of edges) {
    if (!nodeIds.has(edge.source_id) || !nodeIds.has(edge.target_id)) {
      continue;
    }
    const baseWeight = COMMUNITY_EDGE_WEIGHTS[edge.type];
    if (baseWeight === undefined) {
      continue;
    }
    const weight = Math.max(
      MIN_COMMUNITY_EDGE_WEIGHT,
      baseWeight * edge.confidence,
    );
    addUndirectedWeight(adjacency, edge.source_id, edge.target_id, weight);
  }
  return { nodes: nodeIds, adjacency };
}

function partitionWeightedGraph(
  graph: WeightedGraph,
  resolution: number,
): string[][] {
  if (!hasWeightedEdges(graph.adjacency)) {
    return connectedComponents(graph.nodes, graph.adjacency);
  }
  const partitionGraph = new UndirectedGraph<
    Record<string, never>,
    WeightedEdgeAttributes
  >();
  for (const nodeId of graph.nodes) {
    partitionGraph.addNode(nodeId);
  }
  for (const [sourceId, targets] of graph.adjacency) {
    for (const [targetId, weight] of targets) {
      if (sourceId > targetId) {
        continue;
      }
      partitionGraph.addUndirectedEdge(sourceId, targetId, { weight });
    }
  }
  return partitionsFromLouvain(
    runLouvain(partitionGraph, {
      getEdgeWeight: "weight",
      randomWalk: true,
      resolution,
      rng: seededRandom(LOUVAIN_RANDOM_SEED),
    }),
  );
}

function partitionsFromLouvain(mapping: Record<string, number>): string[][] {
  const byCommunity = new Map<number, string[]>();
  for (const [nodeId, communityId] of Object.entries(mapping)) {
    const nodes = byCommunity.get(communityId);
    if (nodes) {
      nodes.push(nodeId);
    } else {
      byCommunity.set(communityId, [nodeId]);
    }
  }
  return [...byCommunity.values()].map((nodeIds) => nodeIds.sort());
}

function partitionWeightedNumberGraph(
  graph: WeightedNumberGraph,
  resolution: number,
): number[][] {
  const stringGraph: WeightedGraph = {
    nodes: new Set([...graph.nodes].map(String)),
    adjacency: new Map(
      [...graph.adjacency.entries()].map(([node, targets]) => [
        String(node),
        new Map(
          [...targets.entries()].map(([target, weight]) => [
            String(target),
            weight,
          ]),
        ),
      ]),
    ),
  };
  return partitionWeightedGraph(stringGraph, resolution).map((partition) =>
    partition
      .map((nodeId) => Number.parseInt(nodeId, 10))
      .filter((nodeId) => Number.isInteger(nodeId))
      .sort((left, right) => left - right),
  );
}

function hasWeightedEdges<K>(adjacency: Map<K, Map<K, number>>): boolean {
  for (const targets of adjacency.values()) {
    if (targets.size > 0) {
      return true;
    }
  }
  return false;
}

function mergeSmallLeafPartitions(
  leafPartitions: string[][],
  communityGraph: WeightedNumberGraph,
): string[][] {
  const merged = leafPartitions.map((nodeIds) => new Set(nodeIds));
  const removed = new Set<number>();
  for (const [index, nodeIds] of merged.entries()) {
    if (removed.has(index) || nodeIds.size >= MIN_CHILD_NODES) {
      continue;
    }
    const target = strongestNeighbor(index, communityGraph, removed);
    if (target === null) {
      continue;
    }
    const weight = communityGraph.adjacency.get(index)?.get(target) ?? 0;
    if (weight < MIN_COMMUNITY_EDGE_WEIGHT) {
      continue;
    }
    for (const nodeId of nodeIds) {
      merged[target]?.add(nodeId);
    }
    removed.add(index);
  }
  return merged.flatMap((nodeIds, index) =>
    removed.has(index) || nodeIds.size === 0 ? [] : [[...nodeIds].sort()],
  );
}

function normalizeParentPartitions(
  parentPartitions: number[][],
  leafPartitions: string[][],
  communityGraph: WeightedNumberGraph,
): number[][] {
  const leafToParent = new Map<number, number>();
  parentPartitions.forEach((partition, parentIndex) => {
    partition.forEach((leafIndex) => leafToParent.set(leafIndex, parentIndex));
  });
  const removedParents = new Set<number>();
  parentPartitions.forEach((partition, parentIndex) => {
    if (partition.length !== 1) {
      return;
    }
    const leafIndex = partition[0];
    if (
      leafIndex === undefined ||
      leafPartitions[leafIndex]!.length >= MIN_PARENT_NODES
    ) {
      return;
    }
    const targetLeaf = strongestNeighbor(leafIndex, communityGraph);
    if (targetLeaf === null) {
      return;
    }
    const targetParent = leafToParent.get(targetLeaf);
    if (targetParent === undefined || targetParent === parentIndex) {
      return;
    }
    parentPartitions[targetParent]!.push(leafIndex);
    leafToParent.set(leafIndex, targetParent);
    removedParents.add(parentIndex);
  });

  return parentPartitions
    .flatMap((partition, index) =>
      removedParents.has(index) || partition.length === 0
        ? []
        : [[...new Set(partition)].sort((left, right) => left - right)],
    )
    .sort(
      (left, right) =>
        partitionNodeCount(right, leafPartitions) -
          partitionNodeCount(left, leafPartitions) ||
        left.join(",").localeCompare(right.join(",")),
    )
    .slice(0, MAX_PARENT_COMMUNITIES);
}

function detectedHierarchy(
  parentPartitions: number[][],
  leafPartitions: string[][],
  nodeById: Map<string, CodeGraphNode>,
  graph: WeightedGraph,
): DetectedCommunity[] {
  const detected: DetectedCommunity[] = [];
  for (const [parentRank, leafIndexes] of parentPartitions.entries()) {
    const parentNodeIds = [
      ...new Set(
        leafIndexes.flatMap((leafIndex) => leafPartitions[leafIndex] ?? []),
      ),
    ].sort();
    if (!parentNodeIds.length) {
      continue;
    }
    const parentKey = communityKey(parentNodeIds);
    detected.push({
      key: parentKey,
      nodeIds: parentNodeIds,
      level: 0,
      parentKey: null,
      rank: parentRank,
    });

    const childPartitions = leafIndexes
      .map((leafIndex) => leafPartitions[leafIndex] ?? [])
      .filter((partition) => partition.length > 0)
      .sort(comparePartitions(nodeById))
      .slice(0, MAX_CHILD_COMMUNITIES_PER_PARENT);
    if (childPartitions.length <= 1) {
      continue;
    }
    for (const [childRank, childNodeIds] of childPartitions.entries()) {
      const childKey = communityKey(childNodeIds);
      detected.push({
        key: childKey,
        nodeIds: [...childNodeIds].sort(),
        level: 1,
        parentKey,
        rank: childRank,
      });
      const detailPartitions = detailPartitionsForChild(
        childNodeIds,
        nodeById,
        graph,
      );
      for (const [detailRank, detailNodeIds] of detailPartitions
        .slice(0, MAX_DETAIL_COMMUNITIES_PER_CHILD)
        .entries()) {
        detected.push({
          key: communityKey(detailNodeIds),
          nodeIds: [...detailNodeIds].sort(),
          level: 2,
          parentKey: childKey,
          rank: detailRank,
        });
      }
    }
  }
  return detected.slice(0, MAX_TOTAL_COMMUNITIES);
}

function detailPartitionsForChild(
  nodeIds: string[],
  nodeById: Map<string, CodeGraphNode>,
  graph: WeightedGraph,
): string[][] {
  if (
    nodeIds.length < DETAIL_SPLIT_NODE_THRESHOLD &&
    fileCount(nodeIds, nodeById) < DETAIL_SPLIT_FILE_THRESHOLD
  ) {
    return [];
  }
  const nodeSet = new Set(nodeIds);
  const subgraph: WeightedGraph = {
    nodes: nodeSet,
    adjacency: new Map(
      nodeIds.map((nodeId) => [nodeId, new Map<string, number>()]),
    ),
  };
  for (const nodeId of nodeIds) {
    for (const [targetId, weight] of graph.adjacency.get(nodeId) ?? []) {
      if (nodeId < targetId && nodeSet.has(targetId)) {
        addUndirectedWeight(subgraph.adjacency, nodeId, targetId, weight);
      }
    }
  }
  const partitions = rankPartitions(
    partitionWeightedGraph(subgraph, DETAIL_RESOLUTION),
    nodeById,
  ).filter((partition) => partition.length >= MIN_DETAIL_NODES);
  return partitions.length > 1 ? partitions : [];
}

type WeightedNumberGraph = {
  nodes: Set<number>;
  adjacency: Map<number, Map<number, number>>;
};

function buildPartitionGraph(
  sourceGraph: WeightedGraph,
  leafPartitions: string[][],
): WeightedNumberGraph {
  const nodes = new Set<number>();
  const adjacency = new Map<number, Map<number, number>>();
  const nodeToLeaf = new Map<string, number>();
  leafPartitions.forEach((nodeIds, index) => {
    nodes.add(index);
    adjacency.set(index, new Map());
    nodeIds.forEach((nodeId) => nodeToLeaf.set(nodeId, index));
  });

  for (const [sourceId, targets] of sourceGraph.adjacency) {
    const sourceLeaf = nodeToLeaf.get(sourceId);
    if (sourceLeaf === undefined) {
      continue;
    }
    for (const [targetId, weight] of targets) {
      if (sourceId > targetId) {
        continue;
      }
      const targetLeaf = nodeToLeaf.get(targetId);
      if (targetLeaf === undefined || targetLeaf === sourceLeaf) {
        continue;
      }
      addUndirectedWeight(adjacency, sourceLeaf, targetLeaf, weight);
    }
  }

  return { nodes, adjacency };
}

function connectedComponents<T>(
  nodes: Set<T>,
  adjacency: Map<T, Map<T, number>>,
): T[][] {
  const remaining = new Set(nodes);
  const components: T[][] = [];
  for (const start of nodes) {
    if (!remaining.has(start)) {
      continue;
    }
    const component: T[] = [];
    const stack = [start];
    remaining.delete(start);
    while (stack.length) {
      const node = stack.pop()!;
      component.push(node);
      for (const neighbor of adjacency.get(node)?.keys() ?? []) {
        if (!remaining.has(neighbor)) {
          continue;
        }
        remaining.delete(neighbor);
        stack.push(neighbor);
      }
    }
    components.push(component.sort());
  }
  return components;
}

function rankPartitions(
  partitions: string[][],
  nodeById: Map<string, CodeGraphNode>,
): string[][] {
  return partitions
    .map((partition) => [...partition].sort())
    .sort(comparePartitions(nodeById));
}

function rankNumberPartitions(
  partitions: number[][],
  leafPartitions: string[][],
): number[][] {
  return partitions
    .map((partition) => [...partition].sort((left, right) => left - right))
    .sort(
      (left, right) =>
        partitionNodeCount(right, leafPartitions) -
          partitionNodeCount(left, leafPartitions) ||
        left.join(",").localeCompare(right.join(",")),
    );
}

function comparePartitions(
  nodeById: Map<string, CodeGraphNode>,
): (left: string[], right: string[]) => number {
  return (left, right) =>
    right.length - left.length ||
    communitySortLabel(left, nodeById).localeCompare(
      communitySortLabel(right, nodeById),
    );
}

function strongestNeighbor(
  node: number,
  graph: WeightedNumberGraph,
  removed: Set<number> = new Set(),
): number | null {
  const candidates = [...(graph.adjacency.get(node)?.entries() ?? [])].filter(
    ([candidate]) => !removed.has(candidate),
  );
  if (!candidates.length) {
    return null;
  }
  return candidates.sort(
    ([leftId, leftWeight], [rightId, rightWeight]) =>
      rightWeight - leftWeight || leftId - rightId,
  )[0]![0];
}

function partitionNodeCount(
  partition: number[],
  leafPartitions: string[][],
): number {
  return partition.reduce(
    (sum, leafIndex) => sum + (leafPartitions[leafIndex]?.length ?? 0),
    0,
  );
}

function addUndirectedWeight<K>(
  adjacency: Map<K, Map<K, number>>,
  source: K,
  target: K,
  weight: number,
): void {
  if (source === target) {
    return;
  }
  const sourceTargets = adjacency.get(source);
  const targetSources = adjacency.get(target);
  if (!sourceTargets || !targetSources) {
    return;
  }
  sourceTargets.set(target, (sourceTargets.get(target) ?? 0) + weight);
  targetSources.set(source, (targetSources.get(source) ?? 0) + weight);
}

function communitySortLabel(
  nodeIds: string[],
  nodeById: Map<string, CodeGraphNode>,
): string {
  const labels = nodeIds.flatMap((nodeId) => {
    const node = nodeById.get(nodeId);
    return node ? [node.file_path || node.name] : [];
  });
  return labels.length ? labels.sort()[0]! : "";
}

function fileCount(
  nodeIds: string[],
  nodeById: Map<string, CodeGraphNode>,
): number {
  return new Set(
    nodeIds.flatMap((nodeId) => {
      const filePath = nodeById.get(nodeId)?.file_path;
      return filePath ? [filePath] : [];
    }),
  ).size;
}

export function buildCommunityEdges(
  repoId: string,
  communities: GraphCommunity[],
  codeEdges: CodeGraphEdge[],
): GraphCommunityEdge[] {
  const containsEdges = communities.flatMap((community) => {
    if (!community.parent_id) {
      return [];
    }
    return [
      {
        id: communityEdgeId(
          repoId,
          community.parent_id,
          community.id,
          "contains",
        ),
        repo_id: repoId,
        source_community_id: community.parent_id,
        target_community_id: community.id,
        type: "contains",
        weight: 1,
        confidence: 1,
        reason: "Parent community contains this child community.",
        evidence_edge_ids: [],
        created_at: null,
      } satisfies GraphCommunityEdge,
    ];
  });

  const parentIds = new Set(
    communities
      .map((community) => community.parent_id)
      .filter((id): id is string => Boolean(id)),
  );
  const leaves = communities.filter(
    (community) => !parentIds.has(community.id),
  );
  const nodeToCommunity = new Map<string, string>();
  for (const community of leaves) {
    for (const nodeId of community.node_ids) {
      if (!nodeToCommunity.has(nodeId)) {
        nodeToCommunity.set(nodeId, community.id);
      }
    }
  }

  const aggregates = new Map<string, EdgeAggregate>();
  for (const edge of codeEdges) {
    if (IGNORED_AGGREGATE_EDGE_TYPES.has(edge.type)) {
      continue;
    }
    const sourceCommunityId = nodeToCommunity.get(edge.source_id);
    const targetCommunityId = nodeToCommunity.get(edge.target_id);
    if (
      !sourceCommunityId ||
      !targetCommunityId ||
      sourceCommunityId === targetCommunityId
    ) {
      continue;
    }
    const edgeType = COMMUNITY_DEPENDENCY_EDGE_TYPES[edge.type] ?? "depends_on";
    const key = `${sourceCommunityId}\u0000${targetCommunityId}\u0000${edgeType}`;
    const aggregate = getAggregate(aggregates, key);
    aggregate.weight += Math.max(0.01, edge.weight);
    aggregate.confidenceTotal += edge.confidence;
    aggregate.count += 1;
    aggregate.sourceTypes.set(
      edge.type,
      (aggregate.sourceTypes.get(edge.type) ?? 0) + 1,
    );
    if (aggregate.evidenceEdgeIds.length < MAX_EVIDENCE_EDGE_IDS) {
      aggregate.evidenceEdgeIds.push(edge.id);
    }
  }

  const dependencyEdges = [...aggregates.entries()]
    .sort(([left], [right]) => left.localeCompare(right))
    .flatMap(([key, aggregate]) => {
      const [sourceCommunityId, targetCommunityId, edgeType] =
        key.split("\u0000");
      if (!sourceCommunityId || !targetCommunityId || !edgeType) {
        return [];
      }
      const edge: GraphCommunityEdge = {
        id: communityEdgeId(
          repoId,
          sourceCommunityId,
          targetCommunityId,
          edgeType,
        ),
        repo_id: repoId,
        source_community_id: sourceCommunityId,
        target_community_id: targetCommunityId,
        type: edgeType,
        weight: round4(aggregate.weight),
        confidence: round4(
          aggregate.confidenceTotal / Math.max(aggregate.count, 1),
        ),
        reason: aggregateReason(aggregate),
        evidence_edge_ids: aggregate.evidenceEdgeIds,
        created_at: null,
      };
      return [edge];
    });

  return [...containsEdges, ...dependencyEdges];
}

function isCommunityNode(node: CodeGraphNode): boolean {
  return (
    COMMUNITY_NODE_TYPES.has(node.type) &&
    node.file_path.length > 0 &&
    node.metadata.external !== true
  );
}

function communityRecord(
  repoId: string,
  community: DetectedCommunity,
  options: {
    parentId: string | null;
    nodeById: Map<string, CodeGraphNode>;
    createdAt: string;
  },
): CommunityRecord {
  const nodeIds = sortNodeIds(
    [...new Set(community.nodeIds)],
    options.nodeById,
  );
  const name = communityName(nodeIds, options.nodeById);
  const fileTotal = fileCount(nodeIds, options.nodeById);
  const summary = `${nodeIds.length} graph nodes across ${fileTotal} files in ${name}.`;
  return {
    id: digest(`${repoId}:community:${community.level}:${community.key}`),
    repo_id: repoId,
    name,
    level: community.level,
    parent_id: options.parentId,
    rank: community.rank,
    node_ids: nodeIds,
    summary,
    summary_hash: digest(`${community.key}:${nodeIds.join(",")}`),
    created_at: options.createdAt,
    fileCount: fileTotal,
  };
}

function communityName(
  nodeIds: string[],
  nodeById: Map<string, CodeGraphNode>,
): string {
  const paths = [
    ...new Set(
      nodeIds.flatMap((nodeId) => {
        const filePath = nodeById.get(nodeId)?.file_path;
        return filePath ? [filePath] : [];
      }),
    ),
  ].sort();
  if (!paths.length) {
    return "Community";
  }
  const prefix = commonDirectoryPrefix(paths);
  if (prefix) {
    return prefix;
  }
  if (paths.length === 1) {
    return paths[0]!;
  }
  const firstNames = paths.slice(0, 2).map((path) => pathFileName(path));
  return `${firstNames.join(" + ")}${paths.length > 2 ? ` + ${paths.length - 2} more` : ""}`;
}

function commonDirectoryPrefix(paths: string[]): string | null {
  const directories = paths.map((path) => path.split("/").slice(0, -1));
  if (!directories.length || directories.some((parts) => parts.length === 0)) {
    return null;
  }
  const prefix: string[] = [];
  const maxLength = Math.min(...directories.map((parts) => parts.length));
  for (let index = 0; index < maxLength; index += 1) {
    const segment = directories[0]?.[index];
    if (!segment || directories.some((parts) => parts[index] !== segment)) {
      break;
    }
    prefix.push(segment);
  }
  return prefix.length ? prefix.join("/") : null;
}

function pathFileName(path: string): string {
  return path.split("/").filter(Boolean).at(-1) ?? path;
}

function communityKey(nodeIds: string[]): string {
  return digest([...nodeIds].sort().join("|")).slice(0, 16);
}

function stripCommunityRecord(record: CommunityRecord): GraphCommunity {
  return {
    id: record.id,
    repo_id: record.repo_id,
    name: record.name,
    level: record.level,
    parent_id: record.parent_id,
    rank: record.rank,
    node_ids: record.node_ids,
    summary: record.summary,
    summary_hash: record.summary_hash,
    created_at: record.created_at,
  };
}

function sortNodeIds(
  nodeIds: string[],
  nodeById: Map<string, CodeGraphNode>,
): string[] {
  return nodeIds.sort((leftId, rightId) => {
    const left = nodeById.get(leftId);
    const right = nodeById.get(rightId);
    if (!left || !right) {
      return leftId.localeCompare(rightId);
    }
    return (
      left.file_path.localeCompare(right.file_path) ||
      (left.start_line ?? 0) - (right.start_line ?? 0) ||
      left.type.localeCompare(right.type) ||
      left.name.localeCompare(right.name) ||
      left.id.localeCompare(right.id)
    );
  });
}

function communityEdgeId(
  repoId: string,
  sourceId: string,
  targetId: string,
  edgeType: string,
): string {
  return `${repoId}:community-edge:${digest(`${sourceId}|${targetId}|${edgeType}`).slice(0, 20)}`;
}

function getAggregate(
  aggregates: Map<string, EdgeAggregate>,
  key: string,
): EdgeAggregate {
  const existing = aggregates.get(key);
  if (existing) {
    return existing;
  }
  const created: EdgeAggregate = {
    weight: 0,
    confidenceTotal: 0,
    count: 0,
    evidenceEdgeIds: [],
    sourceTypes: new Map<string, number>(),
  };
  aggregates.set(key, created);
  return created;
}

function aggregateReason(aggregate: EdgeAggregate): string {
  const typeCounts = [...aggregate.sourceTypes.entries()]
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([edgeType, count]) => `${count} ${edgeType}`)
    .join(", ");
  return `Aggregated from ${aggregate.count} source graph edges: ${typeCounts}.`;
}

function round4(value: number): number {
  return Math.round(value * 10000) / 10000;
}

function seededRandom(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state += 0x6d2b79f5;
    let value = state;
    value = Math.imul(value ^ (value >>> 15), value | 1);
    value ^= value + Math.imul(value ^ (value >>> 7), value | 61);
    return ((value ^ (value >>> 14)) >>> 0) / 4294967296;
  };
}
