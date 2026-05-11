import type { Edge, Node } from "@xyflow/react";

import type { CodeEdge, CodeNode } from "../api/client";

export type GraphViewMode = "overview" | "file" | "focus";

export type VisualNodeData = CodeVisualData | ContainerVisualData;

export type FlowNode = Node<VisualNodeData, "code" | "container">;
export type FlowEdge = Edge<VisualEdgeData>;

export type VisualGraph = {
  nodes: FlowNode[];
  edges: FlowEdge[];
};

export type VisualEdgeData = {
  edgeType: string;
  count: number;
  rawEdgeIds: string[];
  hasInferred: boolean;
};

export type CodeVisualData = {
  kind: "code";
  label: string;
  nodeType: string;
  summary: string;
  pathLabel: string;
  lineLabel: string;
  countLabel?: string;
  statsLabel?: string;
  accentColor: string;
  codeNode: CodeNode;
  fileId?: string;
  rawNodeIds: string[];
  isSelected: boolean;
  isNeighbor: boolean;
  isFaded: boolean;
  isContained: boolean;
  isExternal: boolean;
  isFocusMode?: boolean;
};

export type ContainerVisualData = {
  kind: "container";
  title: string;
  subtitle: string;
  containerType: "repository" | "directory" | "file" | "dependency" | "focus";
  pathLabel: string;
  countLabel: string;
  statsLabel: string;
  accentColor: string;
  fileId?: string;
  primaryNodeId?: string;
  rawNodeIds: string[];
  isSelected: boolean;
  isNeighbor: boolean;
  isFaded: boolean;
  isFocusedViaChild: boolean;
  isCompact: boolean;
};

export type FilteredGraph = {
  nodes: CodeNode[];
  edges: CodeEdge[];
  nodeIds: Set<string>;
};

export type ContainmentIndex = {
  nodeById: Map<string, CodeNode>;
  childrenByParent: Map<string, string[]>;
  parentByChild: Map<string, string>;
  fileByNode: Map<string, string>;
  descendantsByFile: Map<string, string[]>;
};

export type FileGroup = {
  id: string;
  name: string;
  pathLabel: string;
  files: CodeNode[];
  width: number;
  height: number;
  childPositions: Map<string, { x: number; y: number }>;
};

export type EdgeBucket = {
  id: string;
  source: string;
  target: string;
  type: string;
  count: number;
  rawEdgeIds: string[];
  hasInferred: boolean;
};

export type NodeStats = {
  incoming: number;
  outgoing: number;
  calls: number;
  imports: number;
};

export type FileDetailSymbolSlot = {
  node: CodeNode;
  x: number;
  y: number;
  width: number;
  height: number;
  label: string;
  pathLabel: string;
  summary: string;
  countLabel: string;
};

export type Portal = {
  visualId: string;
  direction: "in" | "out";
  bucket: EdgeBucket;
  node: CodeNode | null;
};
