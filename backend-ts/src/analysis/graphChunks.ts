import type { CodeChunk } from "../types.js";
import { digest } from "./graphUtils.js";

const CHUNK_SIZE_LINES = 120;

export function buildChunks(
  repoId: string,
  nodeId: string,
  filePath: string,
  content: string,
): CodeChunk[] {
  const lines = content.split(/\r?\n/);
  const chunks: CodeChunk[] = [];
  for (let start = 0; start < lines.length; start += CHUNK_SIZE_LINES) {
    const slice = lines.slice(start, start + CHUNK_SIZE_LINES);
    const text = slice.join("\n");
    if (!text.trim()) {
      continue;
    }
    chunks.push({
      id: digest(`${repoId}:chunk:${filePath}:${start + 1}:${digest(text)}`),
      repo_id: repoId,
      node_id: nodeId,
      file_path: filePath,
      start_line: start + 1,
      end_line: start + slice.length,
      content: text,
      content_hash: digest(text),
      token_count: roughTokenCount(text),
    });
  }
  return chunks;
}

function roughTokenCount(value: string): number {
  return Math.max(
    1,
    Math.ceil(value.split(/\s+/).filter(Boolean).length * 1.3),
  );
}
