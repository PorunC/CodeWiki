import type { CodeEdge, CodeNode, GraphCommunity, GraphResponse } from "../../api/types";
import {
  FILE_NODE_HEIGHT,
  FILE_NODE_WIDTH,
  GROUP_HEADER_HEIGHT,
  GROUP_PADDING_X,
  OVERVIEW_COMMUNITY_LIMIT,
  OVERVIEW_EDGE_LIMIT
} from "../constants";
import { aggregateEdges, toFlowEdge } from "../edges";
import { compactFilePath, filePathLabel } from "../formatters";
import { layoutBoxesCached, nodeSize } from "../layout";
import { toCodeVisualData } from "../nodeData";
import { computeStatsByRawNode, computeStatsForNodeIds } from "../stats";
import { nodeTone } from "../styles";
import { collectOverviewFileIds, compareByPath, deriveFileGroups } from "../topology";
import type {
  ContainmentIndex,
  FilteredGraph,
  FlowEdge,
  FlowNode,
  GraphDensityMode,
  VisualGraph
} from "../types";
import { applyVisualState } from "../visualState";

const COMMUNITY_NODE_WIDTH = 330;
const COMMUNITY_NODE_HEIGHT = 174;
const DEPENDENCY_NODE_ID = "dependency:external";
const OTHER_COMMUNITIES_NODE_ID = "community:other";
const OVERVIEW_SKIP_EDGE_TYPES = new Set(["contains", "defines"]);

type CommunityCandidate = {
  id: string;
  community: GraphCommunity | null;
  name: string;
  pathLabel: string;
  rawNodeIds: string[];
  primaryNodeId?: string;
  fileCount: number;
  symbolCount: number;
  edgeScore: number;
};

export async function buildOverviewGraph(
  graph: GraphResponse,
  filtered: FilteredGraph,
  containment: ContainmentIndex,
  selectedVisualId: string | null,
  options: { densityMode?: GraphDensityMode } = {}
): Promise<VisualGraph> {
  const communities = graph.communities ?? [];
  if (communities.length > 0) {
    return buildCommunityOverviewGraph(graph, filtered, containment, selectedVisualId, options);
  }
  return buildDirectoryOverviewGraph(graph, filtered, containment, selectedVisualId, options);
}

async function buildCommunityOverviewGraph(
  graph: GraphResponse,
  filtered: FilteredGraph,
  containment: ContainmentIndex,
  selectedVisualId: string | null,
  options: { densityMode?: GraphDensityMode }
): Promise<VisualGraph> {
  const densityMode = options.densityMode ?? "readable";
  const ranked = rankCommunities(graph.communities ?? [], filtered, containment);
  const visibleCommunities =
    densityMode === "readable" ? ranked.slice(0, OVERVIEW_COMMUNITY_LIMIT) : ranked;
  const hiddenCommunities =
    densityMode === "readable" ? ranked.slice(OVERVIEW_COMMUNITY_LIMIT) : [];
  const candidates =
    hiddenCommunities.length > 0
      ? [...visibleCommunities, collapsedCommunityCandidate(hiddenCommunities)]
      : visibleCommunities;
  const rawToVisualId = communityRawToVisualId(candidates);
  const hasDependencies = filtered.nodes.some((node) => node.type === "module");
  if (hasDependencies) {
    filtered.nodes
      .filter((node) => node.type === "module")
      .forEach((node) => rawToVisualId.set(node.id, DEPENDENCY_NODE_ID));
  }

  let edgeBuckets = aggregateEdges(filtered.edges, rawToVisualId, {
    skipSelfEdges: true,
    skipTypes: OVERVIEW_SKIP_EDGE_TYPES
  });
  if (densityMode === "readable") {
    edgeBuckets = edgeBuckets.slice(0, OVERVIEW_EDGE_LIMIT);
  }

  const topLevelNodes = candidates.map((candidate) => ({
    id: candidate.id,
    width: COMMUNITY_NODE_WIDTH,
    height: COMMUNITY_NODE_HEIGHT
  }));
  if (
    hasDependencies ||
    edgeBuckets.some((edge) => edge.source === DEPENDENCY_NODE_ID || edge.target === DEPENDENCY_NODE_ID)
  ) {
    topLevelNodes.push({ id: DEPENDENCY_NODE_ID, width: 300, height: 170 });
  }

  const positions = await layoutBoxesCached(`overview:communities:${densityMode}`, topLevelNodes, edgeBuckets, "LR", {
    edgesep: 24,
    marginx: 48,
    marginy: 48,
    nodesep: 82,
    ranksep: 132
  });
  const nodes: FlowNode[] = candidates.map((candidate) => {
    const stats = computeStatsForNodeIds(candidate.rawNodeIds, filtered.edges);
    return {
      id: candidate.id,
      type: "container",
      position: positions.get(candidate.id) ?? { x: 0, y: 0 },
      data: {
        kind: "container",
        title: candidate.name,
        subtitle: candidate.community ? "community" : "collapsed communities",
        containerType: "community",
        pathLabel: candidate.pathLabel,
        countLabel: `${candidate.fileCount}`,
        statsLabel: `${stats.incoming} in / ${stats.outgoing} out`,
        accentColor: nodeTone("directory").border,
        primaryNodeId: candidate.primaryNodeId,
        rawNodeIds: candidate.rawNodeIds,
        isSelected: false,
        isNeighbor: false,
        isFaded: false,
        isFocusedViaChild: false,
        isCompact: true
      },
      ...nodeSize(COMMUNITY_NODE_WIDTH, COMMUNITY_NODE_HEIGHT),
      selectable: true,
      draggable: false
    };
  });

  if (hasDependencies) {
    const moduleIds = filtered.nodes.filter((node) => node.type === "module").map((node) => node.id);
    const depStats = computeStatsForNodeIds(moduleIds, filtered.edges);
    nodes.push({
      id: DEPENDENCY_NODE_ID,
      type: "container",
      position: positions.get(DEPENDENCY_NODE_ID) ?? { x: 0, y: 0 },
      data: {
        kind: "container",
        title: "External Dependencies",
        subtitle: "dependency",
        containerType: "dependency",
        pathLabel: "imports collapsed by target module",
        countLabel: `${moduleIds.length}`,
        statsLabel: `${depStats.incoming} imports / ${depStats.outgoing} out`,
        accentColor: nodeTone("module").border,
        rawNodeIds: moduleIds,
        isSelected: false,
        isNeighbor: false,
        isFaded: false,
        isFocusedViaChild: false,
        isCompact: false
      },
      ...nodeSize(300, 170),
      selectable: true,
      draggable: false
    });
  }

  const edges: FlowEdge[] = edgeBuckets.map((bucket) => toFlowEdge(bucket));
  return applyVisualState(nodes, edges, selectedVisualId, "overview");
}

async function buildDirectoryOverviewGraph(
  graph: GraphResponse,
  filtered: FilteredGraph,
  containment: ContainmentIndex,
  selectedVisualId: string | null,
  options: { densityMode?: GraphDensityMode }
): Promise<VisualGraph> {
  const densityMode = options.densityMode ?? "readable";
  const fileIds = collectOverviewFileIds(filtered.nodes, filtered.edges, containment);
  const fileNodes = [...fileIds]
    .map((id) => containment.nodeById.get(id))
    .filter((node): node is CodeNode => Boolean(node))
    .sort(compareByPath);
  const groups = await deriveFileGroups(fileNodes, fileLevelLayoutEdges(filtered.edges, containment, fileIds));
  const fileToGroup = new Map<string, string>();

  groups.forEach((group) => {
    group.files.forEach((file) => fileToGroup.set(file.id, group.id));
  });

  const rawToVisualId = new Map<string, string>();

  graph.nodes.forEach((node) => {
    if (node.type === "module") {
      rawToVisualId.set(node.id, DEPENDENCY_NODE_ID);
      return;
    }

    const fileId = containment.fileByNode.get(node.id);
    if (fileId && fileIds.has(fileId)) {
      rawToVisualId.set(node.id, fileId);
    }
  });

  let edgeBuckets = aggregateEdges(filtered.edges, rawToVisualId, {
    skipSelfEdges: true,
    skipTypes: new Set(["contains"])
  });
  if (densityMode === "readable") {
    edgeBuckets = edgeBuckets.slice(0, OVERVIEW_EDGE_LIMIT);
  }

  const groupEdgeBuckets = aggregateEdges(
    filtered.edges,
    new Map(
      [...rawToVisualId].map(([rawId, visualId]) => {
        const groupId = visualId === DEPENDENCY_NODE_ID ? DEPENDENCY_NODE_ID : fileToGroup.get(visualId);
        return [rawId, groupId ?? visualId];
      })
    ),
    {
      skipSelfEdges: true,
      skipTypes: new Set(["contains"])
    }
  );

  const topLevelNodes = groups.map((group) => ({ id: group.id, width: group.width, height: group.height }));
  const hasDependencies =
    filtered.nodes.some((node) => node.type === "module") ||
    edgeBuckets.some((edge) => edge.source === DEPENDENCY_NODE_ID || edge.target === DEPENDENCY_NODE_ID);

  if (hasDependencies) {
    topLevelNodes.push({ id: DEPENDENCY_NODE_ID, width: 300, height: 190 });
  }

  const topLevelPositions = await layoutBoxesCached(
    `overview:directories:${densityMode}`,
    topLevelNodes,
    groupEdgeBuckets,
    "LR"
  );
  const statsByRawNode = computeStatsByRawNode(graph.edges);
  const nodes: FlowNode[] = [];

  groups.forEach((group) => {
    const position = topLevelPositions.get(group.id) ?? { x: 0, y: 0 };
    const rawNodeIds = group.files.flatMap((file) => [file.id, ...(containment.descendantsByFile.get(file.id) ?? [])]);
    const groupStats = computeStatsForNodeIds(rawNodeIds, filtered.edges);

    nodes.push({
      id: group.id,
      type: "container",
      position,
      data: {
        kind: "container",
        title: group.name,
        subtitle: "folder container",
        containerType: "directory",
        pathLabel: group.pathLabel,
        countLabel: `${group.files.length}`,
        statsLabel: `${groupStats.incoming} in / ${groupStats.outgoing} out`,
        accentColor: nodeTone("directory").border,
        rawNodeIds,
        isSelected: false,
        isNeighbor: false,
        isFaded: false,
        isFocusedViaChild: false,
        isCompact: false
      },
      ...nodeSize(group.width, group.height),
      selectable: true,
      draggable: false
    });

    group.files.forEach((file) => {
      const childPosition = group.childPositions.get(file.id) ?? { x: GROUP_PADDING_X, y: GROUP_HEADER_HEIGHT };
      const descendants = containment.descendantsByFile.get(file.id) ?? [];
      const stats = computeStatsForNodeIds([file.id, ...descendants], filtered.edges);

      nodes.push({
        id: file.id,
        type: "code",
        parentId: group.id,
        extent: "parent",
        position: childPosition,
        data: toCodeVisualData(file, {
          containment,
          fileId: file.id,
          rawNodeIds: [file.id, ...descendants],
          summary: filePathLabel(file),
          pathLabel: filePathLabel(file),
          countLabel: `${descendants.length}`,
          statsLabel: `${stats.calls} calls / ${stats.imports} imports`,
          isContained: true,
          isExternal: false,
          stats: statsByRawNode.get(file.id)
        }),
        ...nodeSize(FILE_NODE_WIDTH, FILE_NODE_HEIGHT),
        selectable: true,
        draggable: false,
        zIndex: 5
      });
    });
  });

  if (hasDependencies) {
    const depPosition = topLevelPositions.get(DEPENDENCY_NODE_ID) ?? { x: 0, y: 0 };
    const moduleIds = filtered.nodes.filter((node) => node.type === "module").map((node) => node.id);
    const depStats = computeStatsForNodeIds(moduleIds, filtered.edges);

    nodes.push({
      id: DEPENDENCY_NODE_ID,
      type: "container",
      position: depPosition,
      data: {
        kind: "container",
        title: "External Dependencies",
        subtitle: "module container",
        containerType: "dependency",
        pathLabel: "imports collapsed by target module",
        countLabel: `${moduleIds.length}`,
        statsLabel: `${depStats.incoming} imports / ${depStats.outgoing} out`,
        accentColor: nodeTone("module").border,
        rawNodeIds: moduleIds,
        isSelected: false,
        isNeighbor: false,
        isFaded: false,
        isFocusedViaChild: false,
        isCompact: false
      },
      ...nodeSize(300, 190),
      selectable: true,
      draggable: false
    });
  }

  const edges: FlowEdge[] = edgeBuckets.map((bucket) => toFlowEdge(bucket));
  return applyVisualState(nodes, edges, selectedVisualId, "overview");
}

function rankCommunities(
  communities: GraphCommunity[],
  filtered: FilteredGraph,
  containment: ContainmentIndex
): CommunityCandidate[] {
  return communities
    .map((community) => communityCandidate(community, filtered, containment))
    .filter((candidate): candidate is CommunityCandidate => Boolean(candidate && candidate.rawNodeIds.length > 0))
    .sort((left, right) => {
      const scoreDelta = right.edgeScore - left.edgeScore;
      if (scoreDelta !== 0) {
        return scoreDelta;
      }
      const fileDelta = right.fileCount - left.fileCount;
      if (fileDelta !== 0) {
        return fileDelta;
      }
      return left.name.localeCompare(right.name);
    });
}

function communityCandidate(
  community: GraphCommunity,
  filtered: FilteredGraph,
  containment: ContainmentIndex
): CommunityCandidate | null {
  const rawNodeIds = community.node_ids.filter((nodeId) => filtered.nodeIds.has(nodeId));
  if (rawNodeIds.length === 0) {
    return null;
  }
  const rawNodeSet = new Set(rawNodeIds);
  const fileIds = new Set<string>();
  rawNodeIds.forEach((nodeId) => {
    const node = containment.nodeById.get(nodeId);
    const fileId = node?.type === "file" ? node.id : containment.fileByNode.get(nodeId);
    if (fileId) {
      fileIds.add(fileId);
    }
  });
  const edgeScore = filtered.edges.reduce((score, edge) => {
    if (OVERVIEW_SKIP_EDGE_TYPES.has(edge.type)) {
      return score;
    }
    const sourceInside = rawNodeSet.has(edge.source);
    const targetInside = rawNodeSet.has(edge.target);
    if (!sourceInside && !targetInside) {
      return score;
    }
    return score + (sourceInside && targetInside ? 0.15 : 1);
  }, 0);

  return {
    id: `community:${community.id}`,
    community,
    name: community.name,
    pathLabel: communityPathLabel([...fileIds], containment),
    rawNodeIds,
    primaryNodeId: primaryNodeId(rawNodeIds, containment),
    fileCount: fileIds.size,
    symbolCount: rawNodeIds.length - fileIds.size,
    edgeScore
  };
}

function collapsedCommunityCandidate(candidates: CommunityCandidate[]): CommunityCandidate {
  const rawNodeIds = candidates.flatMap((candidate) => candidate.rawNodeIds);
  const fileCount = candidates.reduce((sum, candidate) => sum + candidate.fileCount, 0);
  const symbolCount = candidates.reduce((sum, candidate) => sum + candidate.symbolCount, 0);
  const edgeScore = candidates.reduce((sum, candidate) => sum + candidate.edgeScore, 0);
  return {
    id: OTHER_COMMUNITIES_NODE_ID,
    community: null,
    name: "Other Areas",
    pathLabel: `${candidates.length} lower-traffic communities`,
    rawNodeIds,
    primaryNodeId: undefined,
    fileCount,
    symbolCount,
    edgeScore
  };
}

function communityRawToVisualId(candidates: CommunityCandidate[]): Map<string, string> {
  const rawToVisualId = new Map<string, string>();
  candidates.forEach((candidate) => {
    candidate.rawNodeIds.forEach((nodeId) => {
      if (!rawToVisualId.has(nodeId)) {
        rawToVisualId.set(nodeId, candidate.id);
      }
    });
  });
  return rawToVisualId;
}

function communityPathLabel(fileIds: string[], containment: ContainmentIndex): string {
  const labels = fileIds
    .map((fileId) => containment.nodeById.get(fileId))
    .filter((node): node is CodeNode => Boolean(node))
    .sort(compareByPath)
    .slice(0, 3)
    .map((node) => compactFilePath(node.file_path ?? node.name));
  return labels.length > 0 ? labels.join(" / ") : "no files";
}

function primaryNodeId(rawNodeIds: string[], containment: ContainmentIndex): string | undefined {
  const fileNode = rawNodeIds
    .map((nodeId) => containment.nodeById.get(nodeId))
    .find((node) => node?.type === "file");
  return fileNode?.id ?? rawNodeIds[0];
}

function fileLevelLayoutEdges(
  edges: CodeEdge[],
  containment: ContainmentIndex,
  fileIds: Set<string>
): Array<{ source: string; target: string }> {
  return edges.flatMap((edge) => {
    if (edge.type === "contains") {
      return [];
    }
    const source = containment.fileByNode.get(edge.source);
    const target = containment.fileByNode.get(edge.target);
    if (!source || !target || source === target || !fileIds.has(source) || !fileIds.has(target)) {
      return [];
    }
    return [{ source, target }];
  });
}
