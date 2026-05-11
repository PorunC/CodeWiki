import type { CodeNode, GraphResponse } from "../../api/client";
import { FILE_NODE_HEIGHT, FILE_NODE_WIDTH, GROUP_HEADER_HEIGHT, GROUP_PADDING_X } from "../constants";
import { aggregateEdges, toFlowEdge } from "../edges";
import { compactFilePath } from "../formatters";
import { layoutBoxes, nodeSize } from "../layout";
import { toCodeVisualData } from "../nodeData";
import { computeStatsByRawNode, computeStatsForNodeIds } from "../stats";
import { nodeTone } from "../styles";
import { collectOverviewFileIds, compareByPath, deriveFileGroups } from "../topology";
import type { ContainmentIndex, FilteredGraph, FlowEdge, FlowNode, VisualGraph } from "../types";
import { applyVisualState } from "../visualState";

export function buildOverviewGraph(
  graph: GraphResponse,
  filtered: FilteredGraph,
  containment: ContainmentIndex,
  selectedVisualId: string | null
): VisualGraph {
  const fileIds = collectOverviewFileIds(filtered.nodes, filtered.edges, containment);
  const fileNodes = [...fileIds]
    .map((id) => containment.nodeById.get(id))
    .filter((node): node is CodeNode => Boolean(node))
    .sort(compareByPath);
  const groups = deriveFileGroups(fileNodes);
  const fileToGroup = new Map<string, string>();

  groups.forEach((group) => {
    group.files.forEach((file) => fileToGroup.set(file.id, group.id));
  });

  const dependencyNodeId = "dependency:external";
  const rawToVisualId = new Map<string, string>();

  graph.nodes.forEach((node) => {
    if (node.type === "module") {
      rawToVisualId.set(node.id, dependencyNodeId);
      return;
    }

    const fileId = containment.fileByNode.get(node.id);
    if (fileId && fileIds.has(fileId)) {
      rawToVisualId.set(node.id, fileId);
    }
  });

  const edgeBuckets = aggregateEdges(filtered.edges, rawToVisualId, {
    skipSelfEdges: true,
    skipTypes: new Set(["contains"])
  });

  const groupEdgeBuckets = aggregateEdges(
    filtered.edges,
    new Map(
      [...rawToVisualId].map(([rawId, visualId]) => {
        const groupId = visualId === dependencyNodeId ? dependencyNodeId : fileToGroup.get(visualId);
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
    edgeBuckets.some((edge) => edge.source === dependencyNodeId || edge.target === dependencyNodeId);

  if (hasDependencies) {
    topLevelNodes.push({ id: dependencyNodeId, width: 300, height: 190 });
  }

  const topLevelPositions = layoutBoxes(topLevelNodes, groupEdgeBuckets, "LR");
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
          summary: `${descendants.length} symbols in ${compactFilePath(file.file_path ?? file.name)}`,
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
    const depPosition = topLevelPositions.get(dependencyNodeId) ?? { x: 0, y: 0 };
    const moduleIds = filtered.nodes.filter((node) => node.type === "module").map((node) => node.id);
    const depStats = computeStatsForNodeIds(moduleIds, filtered.edges);

    nodes.push({
      id: dependencyNodeId,
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
