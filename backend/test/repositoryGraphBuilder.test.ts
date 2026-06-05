import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { buildCommunityGraph } from "../src/analysis/graphCommunities.js";
import {
  buildRepositoryGraph,
  type RepositoryGraphInputFile,
} from "../src/analysis/repositoryGraphBuilder.js";
import type { CodeGraphEdge, CodeGraphNode } from "../src/types.js";

describe("buildRepositoryGraph", () => {
  it("creates file, symbol, relationship, chunk, and community records", () => {
    const root = mkdtempSync(join(tmpdir(), "codewiki-graph-builder-"));
    mkdirSync(join(root, "src"), { recursive: true });
    writeFileSync(join(root, "README.md"), "# Demo\n");
    writeFileSync(
      join(root, "src", "main.ts"),
      [
        "import { helper } from './util';",
        "export function run() {",
        "  return helper(41);",
        "}",
        "",
      ].join("\n"),
    );
    writeFileSync(
      join(root, "src", "util.ts"),
      "export function helper(x: number) { return x + 1; }\n",
    );

    const graph = buildRepositoryGraph("repo-1", [
      inputFile(root, "README.md", "markdown", false),
      inputFile(root, "src/main.ts", "typescript", true),
      inputFile(root, "src/util.ts", "typescript", true),
    ]);

    const readme = graph.nodes.find(
      (node) => node.file_path === "README.md" && node.type === "config",
    );
    const mainFile = graph.nodes.find(
      (node) => node.file_path === "src/main.ts" && node.type === "file",
    );
    const utilFile = graph.nodes.find(
      (node) => node.file_path === "src/util.ts" && node.type === "file",
    );
    const runSymbol = graph.nodes.find(
      (node) => node.name === "run" && node.type === "function",
    );
    const helperSymbol = graph.nodes.find(
      (node) => node.name === "helper" && node.type === "function",
    );

    expect(readme).toBeTruthy();
    expect(mainFile).toBeTruthy();
    expect(utilFile).toBeTruthy();
    expect(runSymbol).toMatchObject({
      file_path: "src/main.ts",
      language: "typescript",
    });
    expect(helperSymbol).toMatchObject({
      file_path: "src/util.ts",
      language: "typescript",
    });
    expect(graph.nodes.map((node) => node.id)).toEqual([
      ...new Set(graph.nodes.map((node) => node.id)),
    ]);

    expect(graph.edges).toContainEqual(
      expect.objectContaining({
        source_id: mainFile?.id,
        target_id: runSymbol?.id,
        type: "contains",
        is_inferred: false,
      }),
    );
    expect(graph.edges).toContainEqual(
      expect.objectContaining({
        source_id: utilFile?.id,
        target_id: helperSymbol?.id,
        type: "contains",
        is_inferred: false,
      }),
    );
    expect(graph.edges).toContainEqual(
      expect.objectContaining({
        source_id: mainFile?.id,
        target_id: utilFile?.id,
        type: "imports",
        is_inferred: false,
      }),
    );
    expect(graph.edges).toContainEqual(
      expect.objectContaining({
        source_id: mainFile?.id,
        target_id: helperSymbol?.id,
        type: "calls",
        is_inferred: true,
      }),
    );
    expect(graph.edges.map((edge) => edge.id)).toEqual([
      ...new Set(graph.edges.map((edge) => edge.id)),
    ]);

    expect(graph.chunks.map((chunk) => chunk.file_path)).toEqual([
      "README.md",
      "src/main.ts",
      "src/util.ts",
    ]);
    expect(
      graph.chunks.find((chunk) => chunk.file_path === "src/util.ts")?.content,
    ).toContain("helper");

    const readmeCommunity = graph.communities.find(
      (community) =>
        community.level === 0 && community.node_ids.includes(readme?.id ?? ""),
    );
    const srcCommunity = graph.communities.find(
      (community) =>
        community.level === 0 &&
        community.node_ids.includes(mainFile?.id ?? "") &&
        community.node_ids.includes(utilFile?.id ?? ""),
    );

    expect(readmeCommunity?.node_ids).toEqual([readme?.id]);
    expect(srcCommunity?.node_ids).toEqual(
      expect.arrayContaining([
        mainFile?.id,
        utilFile?.id,
        runSymbol?.id,
        helperSymbol?.id,
      ]),
    );
    expect(graph.communities.every((community) => community.level === 0)).toBe(
      true,
    );
    expect(graph.communityEdges).toEqual([]);
  });

  it("builds Louvain parent and child community layers with dependency edges", () => {
    const { nodes, edges, groups } = topologyFixture();
    const graph = buildCommunityGraph("repo-topology", nodes, edges);
    const parents = graph.communities.filter(
      (community) => community.level === 0,
    );
    const children = graph.communities.filter(
      (community) => community.level === 1,
    );
    const parentIds = new Set(parents.map((community) => community.id));

    expect(parents).toHaveLength(Object.keys(groups).length);
    expect(children.length).toBeGreaterThan(parents.length);
    expect(
      children.every((community) => parentIds.has(community.parent_id ?? "")),
    ).toBe(true);

    for (const group of Object.values(groups)) {
      const parent = parents.find((community) =>
        group.every((nodeId) => community.node_ids.includes(nodeId)),
      );
      expect(parent).toBeTruthy();
      const parentChildren = children.filter(
        (community) => community.parent_id === parent?.id,
      );
      expect(parentChildren.length).toBeGreaterThan(1);
      expect(parentChildren.map((community) => community.rank)).toEqual(
        parentChildren.map((_, index) => index),
      );
      const parentNodeIds = new Set(parent?.node_ids ?? []);
      expect(
        parentChildren.every((community) =>
          community.node_ids.every((nodeId) => parentNodeIds.has(nodeId)),
        ),
      ).toBe(true);
    }

    expect(
      graph.communityEdges.filter((edge) => edge.type === "contains"),
    ).toHaveLength(
      graph.communities.filter((community) => community.parent_id).length,
    );
    expect(graph.communityEdges).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ type: "imports_from" }),
        expect.objectContaining({ type: "calls_into" }),
        expect.objectContaining({ type: "depends_on" }),
      ]),
    );
  });

  it("falls back to connected components for graphs without weighted edges", () => {
    const graph = buildCommunityGraph(
      "repo-components",
      [
        graphNode("root-a", "a.ts"),
        graphNode("root-b", "b.ts"),
        graphNode("nested-c", "src/c.ts"),
      ],
      [],
    );

    expect(graph.communities).toHaveLength(3);
    expect(graph.communities.every((community) => community.level === 0)).toBe(
      true,
    );
    expect(graph.communities.map((community) => community.node_ids)).toEqual([
      ["root-a"],
      ["root-b"],
      ["nested-c"],
    ]);
    expect(graph.communityEdges).toEqual([]);
  });

  it("excludes external graph nodes from community detection and aggregation", () => {
    const nodes = [
      graphNode("internal-a", "src/a.ts"),
      graphNode("internal-b", "src/b.ts"),
      graphNode("external-lib", "node_modules/lib/index.d.ts", {
        external: true,
      }),
    ];
    const edges = [
      graphEdge("internal-a", "internal-b", "calls", 1),
      graphEdge("internal-a", "external-lib", "imports", 1),
      graphEdge("external-lib", "internal-b", "references", 1),
    ];

    const graph = buildCommunityGraph("repo-external", nodes, edges);

    expect(graph.communities).toHaveLength(1);
    expect(graph.communities[0]?.node_ids).toEqual([
      "internal-a",
      "internal-b",
    ]);
    expect(
      graph.communities.some((community) =>
        community.node_ids.includes("external-lib"),
      ),
    ).toBe(false);
    expect(graph.communityEdges).toEqual([]);
  });
});

function inputFile(
  root: string,
  path: string,
  language: string,
  isSource: boolean,
): RepositoryGraphInputFile {
  return {
    path,
    absolute_path: join(root, path),
    language,
    is_source: isSource,
    sha256: `${path}-hash`,
    size_bytes: 100,
    modified_at: "2026-01-01T00:00:00.000Z",
  };
}

function topologyFixture(): {
  nodes: CodeGraphNode[];
  edges: CodeGraphEdge[];
  groups: Record<string, string[]>;
} {
  const groups: Record<string, string[]> = {};
  const nodes: CodeGraphNode[] = [];
  for (const [parent, child] of [
    ["alpha", "api"],
    ["alpha", "service"],
    ["beta", "ui"],
    ["beta", "state"],
  ]) {
    const key = `${parent}/${child}`;
    groups[key] = [];
    for (let index = 0; index < 40; index += 1) {
      const id = `${key}:${index}`;
      groups[key].push(id);
      nodes.push(graphNode(id, `${key}/${index}.ts`));
    }
  }

  const edges: CodeGraphEdge[] = [];
  for (const group of Object.values(groups)) {
    for (let index = 0; index < group.length - 1; index += 1) {
      if (index === 19) {
        continue;
      }
      edges.push(graphEdge(group[index]!, group[index + 1]!, "calls", 1));
    }
    edges.push(graphEdge(group[19]!, group[20]!, "references", 0.8));
  }
  edges.push(
    graphEdge(
      groups["alpha/api"]![39]!,
      groups["alpha/service"]![0]!,
      "imports",
      0.33,
    ),
  );
  edges.push(
    graphEdge(
      groups["beta/ui"]![39]!,
      groups["beta/state"]![0]!,
      "imports",
      0.33,
    ),
  );
  edges.push(
    graphEdge(
      groups["alpha/service"]![39]!,
      groups["beta/ui"]![0]!,
      "calls",
      0.01,
    ),
  );

  return { nodes, edges, groups };
}

function graphNode(
  id: string,
  filePath: string,
  metadata: CodeGraphNode["metadata"] = {},
): CodeGraphNode {
  return {
    id,
    repo_id: "repo-topology",
    type: "file",
    name: filePath,
    file_path: filePath,
    start_line: 1,
    end_line: 1,
    language: "typescript",
    symbol_id: null,
    summary: null,
    hash: `${id}:hash`,
    metadata,
  };
}

function graphEdge(
  sourceId: string,
  targetId: string,
  type: string,
  confidence: number,
): CodeGraphEdge {
  return {
    id: `${sourceId}->${targetId}:${type}:${confidence}`,
    repo_id: "repo-topology",
    source_id: sourceId,
    target_id: targetId,
    type,
    confidence,
    weight: confidence,
    is_inferred: type === "calls",
    metadata: {},
  };
}
