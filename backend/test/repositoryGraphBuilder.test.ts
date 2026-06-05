import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  buildRepositoryGraph,
  type RepositoryGraphInputFile,
} from "../src/analysis/repositoryGraphBuilder.js";

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

    expect(graph.communities).toEqual([
      expect.objectContaining({ name: "root", node_ids: [readme?.id] }),
      expect.objectContaining({
        name: "src",
        node_ids: [mainFile?.id, utilFile?.id],
      }),
    ]);
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
