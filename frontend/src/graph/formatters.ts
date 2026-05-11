import type { CodeEdge, CodeNode } from "../api/client";
import type { GraphViewMode } from "./types";

export function formatLineRange(node: CodeNode): string {
  if (node.start_line != null && node.end_line != null) {
    return `${node.start_line}-${node.end_line}`;
  }
  if (node.start_line != null) {
    return `${node.start_line}`;
  }
  return "n/a";
}

export function collectEdgeMetadata(edges: CodeEdge[], edgeType: string, metadataKey: string): string[] {
  return [
    ...new Set(
      edges
        .filter((edge) => edge.type === edgeType)
        .flatMap((edge) => listFromUnknown(edge.metadata[metadataKey]))
    )
  ];
}

export function listFromUnknown(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.map((item) => formatUnknown(item)).filter(Boolean);
  }
  if (value === null || value === undefined || value === "") {
    return [];
  }
  return [formatUnknown(value)];
}

export function formatUnknown(value: unknown): string {
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (value === null || value === undefined) {
    return "";
  }
  return JSON.stringify(value);
}

export function compactFilePath(path: string): string {
  const normalized = path.replaceAll("\\", "/");
  const parts = normalized.split("/").filter(Boolean);
  if (parts.length <= 3) {
    return normalized || "scope";
  }
  return `${parts[0]}/.../${parts.slice(-2).join("/")}`;
}

export function fileDisplayName(node: CodeNode): string {
  const rawPath = node.file_path || node.name || node.symbol_id || "unnamed";
  const normalized = rawPath.replaceAll("\\", "/");
  const parts = normalized.split("/").filter(Boolean);
  return parts.at(-1) || node.name || "unnamed";
}

export function filePathLabel(node: CodeNode): string {
  return (node.file_path || node.name || "source file").replaceAll("\\", "/");
}

export function nodeSummary(node: CodeNode): string {
  const signature = typeof node.metadata.signature === "string" ? node.metadata.signature : "";
  const docstring = typeof node.metadata.docstring === "string" ? node.metadata.docstring : "";
  if (signature) {
    return signature;
  }
  if (docstring) {
    return docstring;
  }
  if (node.type === "module") {
    return "External dependency";
  }
  if (node.type === "file") {
    return filePathLabel(node);
  }
  return compactFilePath(node.file_path ?? node.name);
}

export function symbolSummary(node: CodeNode, fallback: string): string {
  const signature = typeof node.metadata.signature === "string" ? node.metadata.signature : "";
  const docstring = typeof node.metadata.docstring === "string" ? node.metadata.docstring : "";
  if (signature) {
    return signature;
  }
  if (docstring) {
    return docstring;
  }
  return fallback;
}

export function compactSymbolName(node: CodeNode): string {
  const rawName = node.name || node.symbol_id || "unnamed";
  if (node.type === "class") {
    return classDisplayName(node);
  }
  if (node.type === "method") {
    return methodDisplayName(node);
  }
  if (node.type === "function") {
    return functionDisplayName(node);
  }
  const withoutParens = rawName.split("(")[0] || rawName;
  const separators = ["::", "."];

  for (const separator of separators) {
    const index = withoutParens.lastIndexOf(separator);
    if (index >= 0 && index < withoutParens.length - separator.length) {
      return withoutParens.slice(index + separator.length);
    }
  }

  return withoutParens;
}

export function classDisplayName(node: CodeNode): string {
  const signature = typeof node.metadata.signature === "string" ? node.metadata.signature : "";
  const fromSignature = signature.match(/\bclass\s+([A-Za-z_$][\w$]*)/)?.[1];
  return compactQualifiedName(fromSignature || node.name || node.symbol_id || "unnamed");
}

export function methodDisplayName(node: CodeNode): string {
  const signature = typeof node.metadata.signature === "string" ? node.metadata.signature : "";
  const fromSignature =
    signature.match(/\bdef\s+([A-Za-z_$][\w$]*)\s*\(/)?.[1] ??
    signature.match(/\basync\s+def\s+([A-Za-z_$][\w$]*)\s*\(/)?.[1];
  return compactQualifiedName(fromSignature || node.name || node.symbol_id || "unnamed");
}

export function functionDisplayName(node: CodeNode): string {
  const signature = typeof node.metadata.signature === "string" ? node.metadata.signature : "";
  const fromSignature =
    signature.match(/\basync\s+def\s+([A-Za-z_$][\w$]*)\s*\(/)?.[1] ??
    signature.match(/\bdef\s+([A-Za-z_$][\w$]*)\s*\(/)?.[1] ??
    signature.match(/\bfunction\s+([A-Za-z_$][\w$]*)\s*\(/)?.[1];
  return compactQualifiedName(fromSignature || node.name || node.symbol_id || "unnamed");
}

export function compactQualifiedName(value: string): string {
  const withoutKeyword = value.replace(/^(class|def|async\s+def|function|method)\s+/, "");
  const withoutParens = withoutKeyword.split("(")[0] || withoutKeyword;
  const separators = ["::", "."];

  for (const separator of separators) {
    const index = withoutParens.lastIndexOf(separator);
    if (index >= 0 && index < withoutParens.length - separator.length) {
      return withoutParens.slice(index + separator.length);
    }
  }

  return withoutParens;
}

export function modeHint(mode: GraphViewMode): string {
  switch (mode) {
    case "overview":
      return "Files are grouped by readable folders; calls and imports are aggregated.";
    case "file":
      return "This view expands one file in source order and keeps cross-file links as portals.";
    case "focus":
      return "Only the selected node and its one-hop neighborhood are shown.";
  }
}
