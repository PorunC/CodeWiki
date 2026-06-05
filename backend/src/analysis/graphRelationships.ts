import { dirname } from "node:path";
import type { CodeGraphEdge, CodeGraphNode } from "../types.js";
import { codeEdge } from "./graphElements.js";
import type { ImportRecord } from "./sourceParser.js";

export type CallRecord = {
  file_path: string;
  name: string;
  line: number;
};

export function addImportEdges(
  repoId: string,
  edges: CodeGraphEdge[],
  fileNodes: Map<string, CodeGraphNode>,
  imports: ImportRecord[],
): void {
  for (const record of imports) {
    const source = fileNodes.get(record.file_path);
    const target = resolveImportTarget(
      record.file_path,
      record.target,
      fileNodes,
    );
    if (!source || !target) {
      continue;
    }
    edges.push(
      codeEdge(repoId, source.id, target.id, "imports", {
        line: record.line,
        raw: record.raw,
        confidence_level: "medium",
      }),
    );
  }
}

export function addCallEdges(
  repoId: string,
  edges: CodeGraphEdge[],
  fileNodes: Map<string, CodeGraphNode>,
  symbolsByName: Map<string, CodeGraphNode[]>,
  calls: CallRecord[],
): void {
  for (const call of calls) {
    const sourceFile = fileNodes.get(call.file_path);
    const candidates = symbolsByName.get(call.name) ?? [];
    const target =
      candidates.find((candidate) => candidate.file_path === call.file_path) ??
      candidates[0];
    if (!sourceFile || !target || target.id === sourceFile.id) {
      continue;
    }
    edges.push(
      codeEdge(repoId, sourceFile.id, target.id, "calls", {
        line: call.line,
        confidence_level:
          target.file_path === call.file_path ? "medium" : "low",
        reason: "Lightweight call reference detected by name.",
      }),
    );
  }
}

function resolveImportTarget(
  sourcePath: string,
  target: string,
  fileNodes: Map<string, CodeGraphNode>,
): CodeGraphNode | null {
  if (target.startsWith(".")) {
    const sourceDir = dirname(sourcePath);
    const normalizedBase = `${sourceDir}/${target}`
      .replace(/\/\.\//g, "/")
      .replace(/^\.\//, "");
    const candidates = [
      normalizedBase,
      `${normalizedBase}.ts`,
      `${normalizedBase}.tsx`,
      `${normalizedBase}.js`,
      `${normalizedBase}.jsx`,
      `${normalizedBase}.py`,
      `${normalizedBase}/index.ts`,
      `${normalizedBase}/index.tsx`,
      `${normalizedBase}/index.js`,
    ].map((item) => item.replace(/\/+/g, "/").replace(/^\//, ""));
    for (const candidate of candidates) {
      const node = fileNodes.get(candidate);
      if (node) {
        return node;
      }
    }
  }
  const suffix = target.replace(/\./g, "/");
  for (const [path, node] of fileNodes) {
    if (
      path.endsWith(`${suffix}.py`) ||
      path.endsWith(`${suffix}.ts`) ||
      path.endsWith(`${suffix}.js`)
    ) {
      return node;
    }
  }
  return null;
}
