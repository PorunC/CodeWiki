import type { CodeEdge, CodeNode } from "../api/client";
import {
  FILE_NODE_HEIGHT,
  FILE_NODE_WIDTH,
  GROUP_CHILD_GAP,
  GROUP_HEADER_HEIGHT,
  GROUP_PADDING_X
} from "./constants";
import type { ContainmentIndex, FileGroup } from "./types";

export function collectOverviewFileIds(
  nodes: CodeNode[],
  edges: CodeEdge[],
  containment: ContainmentIndex
): Set<string> {
  const fileIds = new Set<string>();

  nodes.forEach((node) => {
    const fileId = containment.fileByNode.get(node.id);
    if (fileId) {
      fileIds.add(fileId);
    }
  });

  edges.forEach((edge) => {
    const sourceFile = containment.fileByNode.get(edge.source);
    const targetFile = containment.fileByNode.get(edge.target);
    if (sourceFile) {
      fileIds.add(sourceFile);
    }
    if (targetFile) {
      fileIds.add(targetFile);
    }
  });

  return fileIds;
}

export function deriveFileGroups(files: CodeNode[]): FileGroup[] {
  if (files.length === 0) {
    return [];
  }

  let groups = groupFilesByDepth(files, 1);
  if (groups.size < 2 || largestGroupShare(groups, files.length) > 0.7) {
    groups = groupFilesByDepth(files, 2);
  }
  if (groups.size < 2 || largestGroupShare(groups, files.length) > 0.7) {
    groups = groupFilesByDepth(files, 3);
  }

  return [...groups.entries()]
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([groupPath, groupFiles], index) => {
      const cols = clamp(Math.ceil(Math.sqrt(groupFiles.length)), 1, 4);
      const rows = Math.ceil(groupFiles.length / cols);
      const width = GROUP_PADDING_X * 2 + cols * FILE_NODE_WIDTH + (cols - 1) * GROUP_CHILD_GAP;
      const height = GROUP_HEADER_HEIGHT + 28 + rows * FILE_NODE_HEIGHT + (rows - 1) * GROUP_CHILD_GAP;
      const childPositions = new Map<string, { x: number; y: number }>();

      groupFiles.sort(compareByPath).forEach((file, fileIndex) => {
        const col = fileIndex % cols;
        const row = Math.floor(fileIndex / cols);
        childPositions.set(file.id, {
          x: GROUP_PADDING_X + col * (FILE_NODE_WIDTH + GROUP_CHILD_GAP),
          y: GROUP_HEADER_HEIGHT + 24 + row * (FILE_NODE_HEIGHT + GROUP_CHILD_GAP)
        });
      });

      return {
        id: `group:${index}:${groupPath}`,
        name: groupPath === "~" ? "(root)" : groupPath,
        pathLabel: groupPath === "~" ? "repository root" : groupPath,
        files: groupFiles,
        width,
        height,
        childPositions
      };
    });
}

function groupFilesByDepth(files: CodeNode[], depth: number): Map<string, CodeNode[]> {
  const prefix = commonDirectoryPrefix(files.map((file) => file.file_path ?? file.name));
  const groups = new Map<string, CodeNode[]>();

  files.forEach((file) => {
    const path = file.file_path ?? file.name;
    const stripped = stripPrefix(path, prefix);
    const parts = stripped.split("/").filter(Boolean);
    const dirParts = parts.length > 1 ? parts.slice(0, -1) : [];
    const key = dirParts.length === 0 ? "~" : dirParts.slice(0, depth).join("/");
    const groupFiles = groups.get(key) ?? [];
    groupFiles.push(file);
    groups.set(key, groupFiles);
  });

  return groups;
}

export function compareByPath(left: CodeNode, right: CodeNode): number {
  return (left.file_path ?? left.name).localeCompare(right.file_path ?? right.name);
}

export function compareBySourceOrder(left?: CodeNode, right?: CodeNode): number {
  if (!left && !right) {
    return 0;
  }
  if (!left) {
    return 1;
  }
  if (!right) {
    return -1;
  }
  const leftPath = left.file_path ?? "";
  const rightPath = right.file_path ?? "";
  if (leftPath !== rightPath) {
    return leftPath.localeCompare(rightPath);
  }
  const leftLine = left.start_line ?? Number.MAX_SAFE_INTEGER;
  const rightLine = right.start_line ?? Number.MAX_SAFE_INTEGER;
  if (leftLine !== rightLine) {
    return leftLine - rightLine;
  }
  return left.name.localeCompare(right.name);
}

function largestGroupShare(groups: Map<string, CodeNode[]>, total: number): number {
  if (total === 0) {
    return 0;
  }
  return Math.max(...[...groups.values()].map((nodes) => nodes.length)) / total;
}

function commonDirectoryPrefix(paths: string[]): string {
  const dirs = paths
    .filter(Boolean)
    .map((path) => path.replaceAll("\\", "/"))
    .map((path) => {
      const slash = path.lastIndexOf("/");
      return slash >= 0 ? path.slice(0, slash + 1) : "";
    });

  if (dirs.length === 0) {
    return "";
  }

  let prefix = dirs[0];
  dirs.forEach((dir) => {
    while (prefix && !dir.startsWith(prefix)) {
      prefix = prefix.slice(0, -1);
      const slash = prefix.lastIndexOf("/");
      prefix = slash >= 0 ? prefix.slice(0, slash + 1) : "";
    }
  });

  return prefix;
}

function stripPrefix(value: string, prefix: string): string {
  const normalized = value.replaceAll("\\", "/");
  return prefix && normalized.startsWith(prefix) ? normalized.slice(prefix.length) : normalized;
}

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}
