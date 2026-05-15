import type { CodeEdge, CodeNode, GraphResponse } from "../../api/types";
import {
  DRILLDOWN_EDGE_LIMIT,
  FILE_CONTAINER_MIN_HEIGHT,
  FILE_CONTAINER_MIN_WIDTH,
  FILE_NODE_HEIGHT,
  FILE_NODE_WIDTH,
  GROUP_HEADER_HEIGHT,
  GROUP_PADDING_X,
  SYMBOL_NODE_HEIGHT,
  SYMBOL_NODE_WIDTH
} from "../constants";
import { aggregateEdges, toFlowEdge } from "../edges";
import { fileDisplayName, filePathLabel, formatLineRange, isFileLikeNode, nodeSummary } from "../formatters";
import { layoutBoxesCached, measureLayoutBounds, nodeSize, normalizeLayoutPositions } from "../layout";
import { toCodeVisualData } from "../nodeData";
import { computeStatsByRawNode, computeStatsForNodeIds } from "../stats";
import { nodeTone } from "../styles";
import { compareByPath, compareBySourceOrder } from "../topology";
import type {
  ContainmentIndex,
  DrilldownContainerSelection,
  FilteredGraph,
  FlowNode,
  GraphDensityMode,
  VisualGraph
} from "../types";
import { applyVisualState } from "../visualState";
import { buildOverviewGraph } from "./overviewGraph";

const DRILLDOWN_MIN_WIDTH = 900;
const DRILLDOWN_MIN_HEIGHT = 560;

type FileDrilldownContext = {
  file: CodeNode;
  fileContainerId: string;
  descendants: string[];
  visibleSymbols: CodeNode[];
  symbolPositions: Map<string, { x: number; y: number }>;
  width: number;
  height: number;
};

export function drilldownRootVisualId(containerId: string): string {
  return `drilldown:${containerId}`;
}

export async function buildContainerDrilldownGraph(
  graph: GraphResponse,
  filtered: FilteredGraph,
  containment: ContainmentIndex,
  drilldownContainer: DrilldownContainerSelection | null,
  selectedVisualId: string | null,
  options: { densityMode?: GraphDensityMode } = {}
): Promise<VisualGraph> {
  if (!drilldownContainer) {
    return buildOverviewGraph(graph, filtered, containment, selectedVisualId, options);
  }

  const rawIds = new Set(drilldownContainer.rawNodeIds);
  const fileNodes = drilldownContainer.rawNodeIds
    .map((id) => containment.nodeById.get(id))
    .filter((node): node is CodeNode => Boolean(node))
    .filter((node) => isFileLikeNode(node) && filtered.nodeIds.has(node.id))
    .sort(compareByPath);

  if (fileNodes.length === 0) {
    return buildOverviewGraph(graph, filtered, containment, selectedVisualId, options);
  }

  const fileContexts = await Promise.all(
    fileNodes.map((file) => buildFileContext(file, rawIds, filtered.edges, containment, drilldownContainer.id))
  );
  const fileBoxes = fileContexts.map((context) => ({
    id: context.fileContainerId,
    width: context.width,
    height: context.height
  }));
  const fileContainerByFile = new Map(fileContexts.map((context) => [context.file.id, context.fileContainerId]));
  const fileLayoutEdges = fileLevelLayoutEdges(filtered.edges, containment, new Set(fileNodes.map((file) => file.id))).map(
    (edge) => ({
      source: fileContainerByFile.get(edge.source) ?? edge.source,
      target: fileContainerByFile.get(edge.target) ?? edge.target
    })
  );
  const rawFilePositions = await layoutBoxesCached(
    `drilldown:${drilldownContainer.id}:files`,
    fileBoxes,
    fileLayoutEdges,
    "LR",
    {
      edgesep: 28,
      marginx: 0,
      marginy: 0,
      nodesep: 72,
      ranksep: 128
    }
  );
  const filePositions = normalizeLayoutPositions(rawFilePositions, fileBoxes, GROUP_PADDING_X, GROUP_HEADER_HEIGHT + 30);
  const fileBounds = measureLayoutBounds(filePositions, fileBoxes);
  const rootId = drilldownRootVisualId(drilldownContainer.id);
  const rootWidth = Math.max(DRILLDOWN_MIN_WIDTH, fileBounds.width + GROUP_PADDING_X * 2);
  const rootHeight = Math.max(DRILLDOWN_MIN_HEIGHT, fileBounds.height + GROUP_HEADER_HEIGHT + 60);
  const statsByRawNode = computeStatsByRawNode(graph.edges);
  const rootStats = computeStatsForNodeIds(drilldownContainer.rawNodeIds, filtered.edges);
  const nodes: FlowNode[] = [
    {
      id: rootId,
      type: "container",
      position: { x: 0, y: 0 },
      data: {
        kind: "container",
        title: drilldownContainer.title,
        subtitle: `${drilldownContainer.containerType} drill-down`,
        containerType: drilldownContainer.containerType,
        pathLabel: drilldownContainer.pathLabel,
        countLabel: `${fileNodes.length}`,
        statsLabel: `${rootStats.incoming} in / ${rootStats.outgoing} out`,
        accentColor: nodeTone("directory").border,
        rawNodeIds: drilldownContainer.rawNodeIds,
        isSelected: false,
        isNeighbor: false,
        isFaded: false,
        isFocusedViaChild: false,
        isCompact: false
      },
      ...nodeSize(rootWidth, rootHeight),
      selectable: true,
      draggable: false
    }
  ];

  fileContexts.forEach((context) => {
    const fileRawIds = [context.file.id, ...context.descendants];
    const fileStats = computeStatsForNodeIds(fileRawIds, filtered.edges);
    nodes.push({
      id: context.fileContainerId,
      type: "container",
      parentId: rootId,
      extent: "parent",
      position: filePositions.get(context.fileContainerId) ?? { x: GROUP_PADDING_X, y: GROUP_HEADER_HEIGHT + 30 },
      data: {
        kind: "container",
        title: fileDisplayName(context.file),
        subtitle: context.file.type === "config" ? "config container" : "file container",
        containerType: "file",
        pathLabel: filePathLabel(context.file),
        countLabel: `${context.visibleSymbols.length}`,
        statsLabel: `${fileStats.calls} calls / ${fileStats.imports} imports`,
        accentColor: nodeTone(context.file.type).border,
        fileId: context.file.id,
        primaryNodeId: context.file.id,
        rawNodeIds: fileRawIds,
        isSelected: false,
        isNeighbor: false,
        isFaded: false,
        isFocusedViaChild: false,
        isCompact: false
      },
      ...nodeSize(context.width, context.height),
      selectable: true,
      draggable: false,
      zIndex: 4
    });

    context.visibleSymbols.forEach((symbol) => {
      nodes.push({
        id: symbol.id,
        type: "code",
        parentId: context.fileContainerId,
        extent: "parent",
        position: context.symbolPositions.get(symbol.id) ?? { x: GROUP_PADDING_X, y: GROUP_HEADER_HEIGHT + 24 },
        data: toCodeVisualData(symbol, {
          containment,
          fileId: context.file.id,
          rawNodeIds: [symbol.id],
          summary: nodeSummary(symbol),
          countLabel: formatLineRange(symbol),
          pathLabel: filePathLabel(symbol),
          stats: statsByRawNode.get(symbol.id),
          isContained: true,
          isExternal: false
        }),
        ...nodeSize(SYMBOL_NODE_WIDTH, SYMBOL_NODE_HEIGHT),
        selectable: true,
        draggable: false,
        zIndex: 8
      });
    });
  });

  const rawToVisual = new Map<string, string>();
  fileContexts.forEach((context) => {
    rawToVisual.set(context.file.id, context.fileContainerId);
    context.descendants.forEach((nodeId) => rawToVisual.set(nodeId, context.fileContainerId));
    context.visibleSymbols.forEach((node) => rawToVisual.set(node.id, node.id));
  });

  let edgeBuckets = aggregateEdges(filtered.edges, rawToVisual, {
    skipSelfEdges: true,
    skipTypes: new Set(["contains"])
  });
  if ((options.densityMode ?? "readable") === "readable") {
    edgeBuckets = edgeBuckets.slice(0, DRILLDOWN_EDGE_LIMIT);
  }
  const edges = edgeBuckets.map((bucket) => toFlowEdge(bucket));

  return applyVisualState(nodes, edges, selectedVisualId, "drilldown");
}

async function buildFileContext(
  file: CodeNode,
  drilldownRawIds: Set<string>,
  edges: CodeEdge[],
  containment: ContainmentIndex,
  containerId: string
): Promise<FileDrilldownContext> {
  const descendants = (containment.descendantsByFile.get(file.id) ?? []).filter((nodeId) => drilldownRawIds.has(nodeId));
  const visibleSymbols = descendants
    .map((nodeId) => containment.nodeById.get(nodeId))
    .filter((node): node is CodeNode => Boolean(node))
    .filter((node) => node.type === "class" || node.type === "function" || node.type === "method")
    .sort(compareBySourceOrder);
  const symbolBoxes = visibleSymbols.map((node) => ({
    id: node.id,
    width: SYMBOL_NODE_WIDTH,
    height: SYMBOL_NODE_HEIGHT
  }));
  const symbolIds = new Set(visibleSymbols.map((node) => node.id));
  const symbolEdges = edges.filter(
    (edge) => edge.type !== "contains" && symbolIds.has(edge.source) && symbolIds.has(edge.target)
  );
  const rawPositions = await layoutBoxesCached(
    `drilldown:${containerId}:symbols:${file.id}`,
    symbolBoxes,
    symbolEdges,
    "TB",
    {
      edgesep: 16,
      marginx: 0,
      marginy: 0,
      nodesep: 16,
      ranksep: 34
    }
  );
  const symbolPositions = normalizeLayoutPositions(rawPositions, symbolBoxes, GROUP_PADDING_X, GROUP_HEADER_HEIGHT + 24);
  const symbolBounds = measureLayoutBounds(symbolPositions, symbolBoxes);

  return {
    file,
    fileContainerId: `drill-file:${file.id}`,
    descendants,
    visibleSymbols,
    symbolPositions,
    width: Math.max(FILE_CONTAINER_MIN_WIDTH, symbolBounds.width + GROUP_PADDING_X * 2, FILE_NODE_WIDTH + GROUP_PADDING_X),
    height: Math.max(FILE_CONTAINER_MIN_HEIGHT, symbolBounds.height + GROUP_HEADER_HEIGHT + 42, FILE_NODE_HEIGHT)
  };
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
