import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { isWikiNoiseFile } from "../services/fileRoles.js";
import type { CodeChunk, CodeGraphNode } from "../types.js";

const CHUNK_SOURCE_NODE_TYPES = new Set([
  "config",
  "class",
  "function",
  "method",
  "schema",
  "endpoint",
]);

export function buildSourceChunks(
  repoId: string,
  repoPath: string,
  nodes: CodeGraphNode[],
): CodeChunk[] {
  const root = resolve(repoPath);
  const linesByFile = new Map<string, string[]>();
  const seen = new Set<string>();
  const chunks: CodeChunk[] = [];
  for (const node of [...nodes].sort(
    (left, right) =>
      Number(left.type === "file") - Number(right.type === "file"),
  )) {
    if (!CHUNK_SOURCE_NODE_TYPES.has(node.type) || !node.file_path) {
      continue;
    }
    if (isWikiNoiseFile(node.file_path)) {
      continue;
    }
    let lines = linesByFile.get(node.file_path);
    if (!lines) {
      const absolutePath = resolve(root, node.file_path);
      if (!isPathInside(root, absolutePath)) {
        linesByFile.set(node.file_path, []);
        continue;
      }
      lines = readFileLines(absolutePath);
      linesByFile.set(node.file_path, lines);
    }
    if (!lines.length) {
      continue;
    }
    const startLine = clampLine(node.start_line ?? 1, lines.length);
    const endLine = Math.max(
      startLine,
      clampLine(node.end_line ?? startLine, lines.length),
    );
    const content = `${lines.slice(startLine - 1, endLine).join("\n")}\n`;
    if (!content.trim()) {
      continue;
    }
    const contentHash = sha256(content);
    const dedupeKey = [node.file_path, startLine, endLine, contentHash].join(
      "\0",
    );
    if (seen.has(dedupeKey)) {
      continue;
    }
    seen.add(dedupeKey);
    chunks.push({
      id: sourceChunkId(
        repoId,
        node.id,
        node.file_path,
        startLine,
        endLine,
        contentHash,
      ),
      repo_id: repoId,
      node_id: node.id,
      file_path: node.file_path,
      start_line: startLine,
      end_line: endLine,
      content,
      content_hash: contentHash,
      token_count: estimateTokens(content),
    });
  }
  return chunks.sort(
    (left, right) =>
      left.file_path.localeCompare(right.file_path) ||
      left.start_line - right.start_line ||
      left.end_line - right.end_line,
  );
}

function sourceChunkId(
  repoId: string,
  nodeId: string,
  filePath: string,
  startLine: number,
  endLine: number,
  contentHash: string,
): string {
  return `${repoId}:chunk:${sha1(
    [nodeId, filePath, String(startLine), String(endLine), contentHash].join(
      "|",
    ),
  ).slice(0, 24)}`;
}

function readFileLines(path: string): string[] {
  try {
    return readFileSync(path, "utf8").split(/\r?\n/);
  } catch {
    return [];
  }
}

function isPathInside(root: string, path: string): boolean {
  const normalizedRoot = root.endsWith("/") ? root : `${root}/`;
  return path === root || path.startsWith(normalizedRoot);
}

function clampLine(value: number, lineCount: number): number {
  return Math.max(1, Math.min(value, lineCount));
}

function estimateTokens(content: string): number {
  return Math.max(1, content.match(/\S+/g)?.length ?? 0);
}

function sha256(content: string): string {
  return createHash("sha256").update(content).digest("hex");
}

function sha1(content: string): string {
  return createHash("sha1").update(content).digest("hex");
}
