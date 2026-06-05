import { readFileSync } from "node:fs";
import type {
  CodeChunk,
  CodeGraphEdge,
  CodeGraphNode,
  GraphCommunity,
  GraphCommunityEdge,
} from "../types.js";
import { buildChunks } from "./graphChunks.js";
import { buildCommunityGraph } from "./graphCommunities.js";
import {
  codeEdge,
  codeNode,
  dedupeEdges,
  dedupeNodes,
} from "./graphElements.js";
import {
  addCallEdges,
  addImportEdges,
  type CallRecord,
} from "./graphRelationships.js";
import { digest, pushMap } from "./graphUtils.js";
import type { ImportRecord } from "./sourceParser.js";
import { parseSource } from "./sourceParser.js";

export type RepositoryGraphInputFile = {
  path: string;
  absolute_path: string;
  language: string;
  is_source: boolean;
  sha256?: string;
  size_bytes: number;
  modified_at?: string;
};

export type RepositoryGraphBuildResult = {
  nodes: CodeGraphNode[];
  edges: CodeGraphEdge[];
  chunks: CodeChunk[];
  communities: GraphCommunity[];
  communityEdges: GraphCommunityEdge[];
};

export function buildRepositoryGraph(
  repoId: string,
  files: RepositoryGraphInputFile[],
): RepositoryGraphBuildResult {
  const nodes: CodeGraphNode[] = [];
  const edges: CodeGraphEdge[] = [];
  const chunks: CodeChunk[] = [];
  const symbolsByName = new Map<string, CodeGraphNode[]>();
  const fileNodes = new Map<string, CodeGraphNode>();
  const imports: ImportRecord[] = [];
  const calls: CallRecord[] = [];

  for (const file of files) {
    const fileNode = codeNode(repoId, {
      type: file.is_source ? "file" : "config",
      name: file.path,
      file_path: file.path,
      start_line: 1,
      end_line: null,
      language: file.language,
      symbol_id: file.path,
      hash: file.sha256 ?? digest(file.path),
      metadata: {
        parser: "typescript-light",
        absolute_path: file.absolute_path,
        is_source: file.is_source,
        modified_at: file.modified_at ?? "",
        size_bytes: file.size_bytes,
        provenance: { source: "repo-scan" },
      },
    });
    nodes.push(fileNode);
    fileNodes.set(file.path, fileNode);

    const content = readTextFile(file.absolute_path);
    if (!content) {
      continue;
    }
    chunks.push(...buildChunks(repoId, fileNode.id, file.path, content));
    if (!file.is_source) {
      continue;
    }
    const parsed = parseSource(file.path, file.language, content);
    imports.push(...parsed.imports);
    calls.push(...parsed.calls);
    for (const symbol of parsed.symbols) {
      const symbolNode = codeNode(repoId, {
        type: symbol.type,
        name: symbol.name,
        file_path: symbol.file_path,
        start_line: symbol.start_line,
        end_line: symbol.end_line,
        language: symbol.language,
        symbol_id: `${symbol.file_path}:${symbol.name}:${symbol.start_line}`,
        hash: digest(`${symbol.file_path}:${symbol.name}:${symbol.signature}`),
        metadata: {
          signature: symbol.signature,
          parser: "typescript-light",
          provenance: { source: "regex" },
        },
      });
      nodes.push(symbolNode);
      pushMap(symbolsByName, symbol.name, symbolNode);
      edges.push(
        codeEdge(repoId, fileNode.id, symbolNode.id, "contains", {
          reason: "Symbol was detected in this file.",
          confidence_level: "medium",
        }),
      );
    }
  }

  addImportEdges(repoId, edges, fileNodes, imports);
  addCallEdges(repoId, edges, fileNodes, symbolsByName, calls);

  const finalNodes = dedupeNodes(nodes);
  const finalEdges = dedupeEdges(edges);
  const { communities, communityEdges } = buildCommunityGraph(
    repoId,
    finalNodes,
    finalEdges,
  );
  return {
    nodes: finalNodes,
    edges: finalEdges,
    chunks,
    communities,
    communityEdges,
  };
}

function readTextFile(path: string): string {
  try {
    return readFileSync(path, "utf8");
  } catch {
    return "";
  }
}
