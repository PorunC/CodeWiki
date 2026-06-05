import type Database from "better-sqlite3";
import type {
  CodeChunk,
  CodeGraphEdge,
  CodeGraphNode,
  GraphCommunity,
  GraphCommunityEdge,
} from "../types.js";
import {
  chunkFromRow,
  communityEdgeFromRow,
  communityFromRow,
  edgeFromRow,
  nodeFromRow,
  scoreNode,
  stringifyJson,
  type Row,
} from "./mappers.js";

export type GraphSearchFilters = {
  types?: string[];
  languages?: string[];
  pathFilters?: string[];
  nameFilters?: string[];
  limit?: number;
};

export class GraphRepository {
  constructor(private readonly db: Database.Database) {}

  replaceGraph(
    repoId: string,
    options: {
      nodes: CodeGraphNode[];
      edges: CodeGraphEdge[];
      chunks?: CodeChunk[];
    },
  ): void {
    const tx = this.db.transaction(() => {
      this.db.prepare("DELETE FROM code_edge WHERE repo_id = ?").run(repoId);
      this.db.prepare("DELETE FROM code_node WHERE repo_id = ?").run(repoId);
      this.db
        .prepare("DELETE FROM code_node_fts WHERE repo_id = ?")
        .run(repoId);

      const insertNode = this.db.prepare(
        `
        INSERT INTO code_node (
          id, repo_id, type, name, file_path, start_line, end_line, language,
          symbol_id, summary, hash, metadata_json
        )
        VALUES (
          @id, @repo_id, @type, @name, @file_path, @start_line, @end_line, @language,
          @symbol_id, @summary, @hash, @metadata_json
        )
        `,
      );
      const insertNodeFts = this.db.prepare(
        `
        INSERT INTO code_node_fts (
          id, repo_id, type, name, file_path, language, symbol_id, summary, signature, docstring
        )
        VALUES (@id, @repo_id, @type, @name, @file_path, @language, @symbol_id, @summary, '', '')
        `,
      );
      for (const node of options.nodes) {
        insertNode.run({
          ...node,
          metadata_json: stringifyJson(node.metadata),
        });
        insertNodeFts.run({
          id: node.id,
          repo_id: node.repo_id,
          type: node.type,
          name: node.name,
          file_path: node.file_path,
          language: node.language ?? "",
          symbol_id: node.symbol_id ?? "",
          summary: node.summary ?? "",
        });
      }

      const insertEdge = this.db.prepare(
        `
        INSERT INTO code_edge (
          id, repo_id, source_id, target_id, type, confidence, weight, is_inferred, metadata_json
        )
        VALUES (
          @id, @repo_id, @source_id, @target_id, @type, @confidence, @weight,
          @is_inferred, @metadata_json
        )
        `,
      );
      for (const edge of options.edges) {
        insertEdge.run({
          ...edge,
          is_inferred: edge.is_inferred ? 1 : 0,
          metadata_json: stringifyJson(edge.metadata),
        });
      }

      if (options.chunks) {
        this.replaceCodeChunksInTransaction(repoId, options.chunks);
      }
    });
    tx();
  }

  getGraph(repoId: string): { nodes: CodeGraphNode[]; edges: CodeGraphEdge[] } {
    const nodes = (
      this.db
        .prepare(
          "SELECT * FROM code_node WHERE repo_id = ? ORDER BY file_path, start_line",
        )
        .all(repoId) as Row[]
    ).map(nodeFromRow);
    const edges = (
      this.db
        .prepare(
          "SELECT * FROM code_edge WHERE repo_id = ? ORDER BY type, source_id",
        )
        .all(repoId) as Row[]
    ).map(edgeFromRow);
    return { nodes, edges };
  }

  searchCodeNodes(
    repoId: string,
    query: string,
    filters: GraphSearchFilters = {},
  ): Array<{ node: CodeGraphNode; score: number; reasons: string[] }> {
    const allNodes = this.getGraph(repoId).nodes;
    const normalizedQuery = query.trim().toLowerCase();
    const limit = filters.limit ?? 20;
    return allNodes
      .filter((node) => {
        if (filters.types?.length && !filters.types.includes(node.type)) {
          return false;
        }
        if (
          filters.languages?.length &&
          (!node.language || !filters.languages.includes(node.language))
        ) {
          return false;
        }
        if (
          filters.pathFilters?.length &&
          !filters.pathFilters.some((item) => node.file_path.includes(item))
        ) {
          return false;
        }
        if (
          filters.nameFilters?.length &&
          !filters.nameFilters.some((item) => node.name.includes(item))
        ) {
          return false;
        }
        if (!normalizedQuery) {
          return true;
        }
        const haystack =
          `${node.name} ${node.file_path} ${node.type} ${node.language ?? ""} ${
            node.summary ?? ""
          }`.toLowerCase();
        return haystack.includes(normalizedQuery);
      })
      .map((node) => ({
        node,
        score: scoreNode(node, normalizedQuery),
        reasons: normalizedQuery
          ? [`matched ${normalizedQuery}`]
          : ["filter match"],
      }))
      .sort(
        (left, right) =>
          right.score - left.score ||
          left.node.name.localeCompare(right.node.name),
      )
      .slice(0, limit);
  }

  replaceGraphCommunities(repoId: string, communities: GraphCommunity[]): void {
    const tx = this.db.transaction(() => {
      this.db
        .prepare("DELETE FROM graph_community_edge WHERE repo_id = ?")
        .run(repoId);
      this.db
        .prepare("DELETE FROM graph_community WHERE repo_id = ?")
        .run(repoId);
      const insert = this.db.prepare(
        `
        INSERT INTO graph_community (
          id, repo_id, name, level, parent_id, rank, node_ids_json, summary, summary_hash, created_at
        )
        VALUES (
          @id, @repo_id, @name, @level, @parent_id, @rank, @node_ids_json,
          @summary, @summary_hash, @created_at
        )
        `,
      );
      for (const community of communities) {
        insert.run({
          ...community,
          node_ids_json: stringifyJson(community.node_ids),
        });
      }
    });
    tx();
  }

  replaceGraphCommunityEdges(
    repoId: string,
    edges: GraphCommunityEdge[],
  ): void {
    const tx = this.db.transaction(() => {
      this.db
        .prepare("DELETE FROM graph_community_edge WHERE repo_id = ?")
        .run(repoId);
      const insert = this.db.prepare(
        `
        INSERT INTO graph_community_edge (
          id, repo_id, source_community_id, target_community_id, type, weight,
          confidence, reason, evidence_edge_ids_json, created_at
        )
        VALUES (
          @id, @repo_id, @source_community_id, @target_community_id, @type, @weight,
          @confidence, @reason, @evidence_edge_ids_json, @created_at
        )
        `,
      );
      for (const edge of edges) {
        insert.run({
          ...edge,
          evidence_edge_ids_json: stringifyJson(edge.evidence_edge_ids),
        });
      }
    });
    tx();
  }

  listGraphCommunities(repoId: string): GraphCommunity[] {
    return (
      this.db
        .prepare(
          "SELECT * FROM graph_community WHERE repo_id = ? ORDER BY level, rank, name",
        )
        .all(repoId) as Row[]
    ).map(communityFromRow);
  }

  listGraphCommunityEdges(repoId: string): GraphCommunityEdge[] {
    return (
      this.db
        .prepare(
          "SELECT * FROM graph_community_edge WHERE repo_id = ? ORDER BY type, source_community_id",
        )
        .all(repoId) as Row[]
    ).map(communityEdgeFromRow);
  }

  replaceCodeChunks(repoId: string, chunks: CodeChunk[]): void {
    const tx = this.db.transaction(() =>
      this.replaceCodeChunksInTransaction(repoId, chunks),
    );
    tx();
  }

  listCodeChunks(repoId: string): CodeChunk[] {
    return (
      this.db
        .prepare(
          "SELECT * FROM code_chunk WHERE repo_id = ? ORDER BY file_path, start_line",
        )
        .all(repoId) as Row[]
    ).map(chunkFromRow);
  }

  searchCodeChunks(
    repoId: string,
    query: string,
    limit = 10,
  ): Array<{ chunk: CodeChunk; score: number; match_type: string }> {
    const normalized = query.trim().toLowerCase();
    if (!normalized) {
      return this.listCodeChunks(repoId)
        .slice(0, limit)
        .map((chunk) => ({ chunk, score: 0.1, match_type: "recent" }));
    }
    return this.listCodeChunks(repoId)
      .map((chunk) => {
        const haystack = `${chunk.file_path}\n${chunk.content}`.toLowerCase();
        const exact = haystack.includes(normalized);
        const terms = normalized.split(/\s+/).filter(Boolean);
        const termHits = terms.filter((term) => haystack.includes(term)).length;
        return {
          chunk,
          score: (exact ? 3 : 0) + termHits / Math.max(terms.length, 1),
          match_type: exact ? "exact" : "term",
        };
      })
      .filter((hit) => hit.score > 0)
      .sort((left, right) => right.score - left.score)
      .slice(0, limit);
  }

  private replaceCodeChunksInTransaction(
    repoId: string,
    chunks: CodeChunk[],
  ): void {
    this.db.prepare("DELETE FROM code_chunk WHERE repo_id = ?").run(repoId);
    this.db.prepare("DELETE FROM code_chunk_fts WHERE repo_id = ?").run(repoId);
    const insert = this.db.prepare(
      `
      INSERT INTO code_chunk (
        id, repo_id, node_id, file_path, start_line, end_line, content, content_hash, token_count
      )
      VALUES (
        @id, @repo_id, @node_id, @file_path, @start_line, @end_line,
        @content, @content_hash, @token_count
      )
      `,
    );
    const insertFts = this.db.prepare(
      `
      INSERT INTO code_chunk_fts (
        id, repo_id, node_id, file_path, start_line, end_line, content
      )
      VALUES (@id, @repo_id, @node_id, @file_path, @start_line, @end_line, @content)
      `,
    );
    for (const chunk of chunks) {
      insert.run(chunk);
      insertFts.run(chunk);
    }
  }
}
