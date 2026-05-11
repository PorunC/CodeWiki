import type { CodeNode } from "../api/client";
import { compactFilePath, fileDisplayName, filePathLabel, formatLineRange } from "./formatters";
import { nodeTone } from "./styles";
import type { CodeVisualData, ContainmentIndex, NodeStats } from "./types";

export function toCodeVisualData(
  node: CodeNode,
  options: {
    containment: ContainmentIndex;
    label?: string;
    fileId?: string;
    rawNodeIds: string[];
    summary: string;
    countLabel?: string;
    pathLabel?: string;
    lineLabel?: string;
    stats?: NodeStats;
    statsLabel?: string;
    isContained: boolean;
    isExternal: boolean;
  }
): CodeVisualData {
  const tone = nodeTone(node.type);
  const statsLabel =
    options.statsLabel ??
    (options.stats ? `${options.stats.outgoing} out / ${options.stats.incoming} in` : "No visible edges");

  return {
    kind: "code",
    label: options.label ?? (node.type === "file" ? fileDisplayName(node) : node.name),
    nodeType: node.type,
    summary: options.summary,
    pathLabel: options.pathLabel ?? (node.type === "file" ? filePathLabel(node) : compactFilePath(node.file_path ?? node.name)),
    lineLabel: options.lineLabel ?? formatLineRange(node),
    countLabel: options.countLabel,
    statsLabel,
    accentColor: tone.border,
    codeNode: node,
    fileId: options.fileId,
    rawNodeIds: options.rawNodeIds,
    isSelected: false,
    isNeighbor: false,
    isFaded: false,
    isContained: options.isContained,
    isExternal: options.isExternal
  };
}
