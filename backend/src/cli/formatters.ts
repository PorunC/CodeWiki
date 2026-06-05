import type { ConfigPayload } from "../presenters/payloads.js";
import {
  arrayOfRecords,
  displayNumber,
  displayString,
  recordValue,
  stringArray,
} from "./runtime.js";

export function formatConfig(payload: ConfigPayload): string {
  return [
    `CODEWIKI_APP_NAME=${payload.app_name}`,
    `CODEWIKI_DATABASE_URL=${payload.database_url}`,
    `CODEWIKI_STORAGE_DIR=${payload.storage_dir}`,
    `CODEWIKI_HOST=${payload.host}`,
    `CODEWIKI_PORT=${payload.port}`,
    `CODEWIKI_LOG_LEVEL=${payload.log.level}`,
    `CODEWIKI_LOG_FORMAT=${payload.log.format}`,
    `CODEWIKI_LLM__MODE=${payload.llm.mode}`,
    `CODEWIKI_LLM__DEFAULT__MODEL=${payload.llm.default.model}`,
  ].join("\n");
}

export function formatGraphStatus(payload: Record<string, unknown>): string {
  return [
    `Repo: ${displayString(payload.repo_id)}`,
    `Files: ${displayNumber(payload.file_count)}`,
    `Nodes: ${displayNumber(payload.node_count)}`,
    `Edges: ${displayNumber(payload.edge_count)}`,
    `Chunks: ${displayNumber(payload.chunk_count)}`,
  ].join("\n");
}

export function formatRelationships(relationships: unknown): string {
  return arrayOfRecords(relationships)
    .map((relationship) => {
      const sourceRecord = recordValue(relationship.source);
      const targetRecord = recordValue(relationship.target);
      const edgeRecord = recordValue(relationship.edge);
      const source = displayString(
        sourceRecord.name,
        displayString(sourceRecord.id),
      );
      const target = displayString(
        targetRecord.name,
        displayString(targetRecord.id),
      );
      return `${displayString(edgeRecord.type, "edge")}\t${source}\t${target}`;
    })
    .join("\n");
}

export function formatSearchResults(payload: Record<string, unknown>): string {
  return arrayOfRecords(payload.results)
    .map((hit) => {
      const node = recordValue(hit.node);
      const score =
        typeof hit.score === "number" ? hit.score.toFixed(2) : "0.00";
      return `${score}\t${displayString(node.type)}\t${displayString(node.name)}\t${displayString(node.file_path)}`;
    })
    .join("\n");
}

export function formatImpact(payload: Record<string, unknown>): string {
  return arrayOfRecords(payload.nodes)
    .map(
      (node) =>
        `${displayString(node.type)}\t${displayString(node.name)}\t${displayString(node.file_path)}`,
    )
    .join("\n");
}

export function formatAffectedFiles(payload: Record<string, unknown>): string {
  return stringArray(payload.affected_files).join("\n");
}
