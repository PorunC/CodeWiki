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

const TOKEN_RE = /[A-Za-z_][A-Za-z0-9_]*|[0-9]+/g;

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
    const normalizedQuery = query.trim();
    const limit = boundedLimit(filters.limit, 20, 200);
    const types = (filters.types ?? []).filter(Boolean);
    const languages = (filters.languages ?? []).filter(Boolean);
    const pathFilters = (filters.pathFilters ?? [])
      .filter(Boolean)
      .map((item) => item.toLowerCase());
    const nameFilters = (filters.nameFilters ?? [])
      .filter(Boolean)
      .map((item) => item.toLowerCase());

    let hits = normalizedQuery
      ? this.searchCodeNodesFts(repoId, normalizedQuery, {
          types,
          languages,
          limit: Math.max(limit * 5, 50),
        })
      : [];
    if (!hits.length && normalizedQuery) {
      hits = this.searchCodeNodesLike(repoId, normalizedQuery, {
        types,
        languages,
        limit: Math.max(limit * 5, 50),
      });
    }
    if (!normalizedQuery) {
      hits = this.searchCodeNodesByFilters(repoId, {
        types,
        languages,
        limit: Math.max(limit * 5, 50),
      });
    }

    const deduped = new Map<
      string,
      { node: CodeGraphNode; score: number; reasons: string[] }
    >();
    for (const hit of hits
      .map((hit) => ({
        node: hit.node,
        score: scoreNodeHit(hit.node, normalizedQuery, hit.score),
        reasons: hit.reasons,
      }))
      .filter(
        (hit) =>
          (!pathFilters.length ||
            pathFilters.some((item) =>
              hit.node.file_path.toLowerCase().includes(item),
            )) &&
          (!nameFilters.length ||
            nameFilters.some((item) =>
              hit.node.name.toLowerCase().includes(item),
            )),
      )) {
      const current = deduped.get(hit.node.id);
      if (!current || hit.score > current.score) {
        deduped.set(hit.node.id, hit);
      }
    }

    return [...deduped.values()]
      .sort(
        (left, right) =>
          right.score - left.score ||
          left.node.file_path.localeCompare(right.node.file_path) ||
          (left.node.start_line ?? 0) - (right.node.start_line ?? 0) ||
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
    const normalized = query.trim();
    const bounded = boundedLimit(limit, 10, 200);
    const ftsQuery = chunkFtsQuery(normalized);
    if (!ftsQuery) {
      return [];
    }
    const rows = this.db
      .prepare(
        `
        SELECT c.id, c.repo_id, c.node_id, c.file_path, c.start_line, c.end_line,
               c.content, c.content_hash, c.token_count,
               bm25(code_chunk_fts) AS rank
        FROM code_chunk_fts
        JOIN code_chunk c ON c.id = code_chunk_fts.id
        WHERE code_chunk_fts MATCH @ftsQuery AND code_chunk_fts.repo_id = @repoId
        ORDER BY rank
        LIMIT @limit
        `,
      )
      .all({ repoId, ftsQuery, limit: bounded }) as Row[];
    if (rows.length) {
      return rows.map((row, index) => ({
        chunk: chunkFromRow(row),
        score: Math.max(0.1, 1 - index * 0.04),
        match_type: "fts",
      }));
    }
    return this.searchCodeChunksLike(repoId, normalized, bounded);
  }

  private searchCodeNodesFts(
    repoId: string,
    query: string,
    options: { types: string[]; languages: string[]; limit: number },
  ): Array<{ node: CodeGraphNode; score: number; reasons: string[] }> {
    const ftsQuery = nodeFtsQuery(query);
    if (!ftsQuery) {
      return [];
    }
    const filter = nodeFilterSql(repoId, options.types, options.languages);
    const rows = this.db
      .prepare(
        `
        SELECT n.id, n.repo_id, n.type, n.name, n.file_path, n.start_line, n.end_line,
               n.language, n.symbol_id, n.summary, n.hash, n.metadata_json,
               bm25(code_node_fts) AS rank
        FROM code_node_fts
        JOIN code_node n ON n.id = code_node_fts.id
        WHERE code_node_fts MATCH @ftsQuery AND ${filter.where}
        ORDER BY rank
        LIMIT @limit
        `,
      )
      .all({ ...filter.params, ftsQuery, limit: options.limit }) as Row[];
    return rows.map((row, index) => ({
      node: nodeFromRow(row),
      score: Math.max(0.1, 1 - index * 0.02),
      reasons: ["fts"],
    }));
  }

  private searchCodeNodesLike(
    repoId: string,
    query: string,
    options: { types: string[]; languages: string[]; limit: number },
  ): Array<{ node: CodeGraphNode; score: number; reasons: string[] }> {
    const filter = nodeFilterSql(repoId, options.types, options.languages);
    const rows = this.db
      .prepare(
        `
        SELECT n.id, n.repo_id, n.type, n.name, n.file_path, n.start_line, n.end_line,
               n.language, n.symbol_id, n.summary, n.hash, n.metadata_json,
               CASE
                 WHEN lower(n.name) = lower(@query) THEN 1.0
                 WHEN lower(n.name) LIKE lower(@startPattern) THEN 0.85
                 WHEN lower(n.name) LIKE lower(@pattern) THEN 0.72
                 WHEN lower(n.symbol_id) LIKE lower(@pattern) THEN 0.62
                 WHEN lower(n.file_path) LIKE lower(@pattern) THEN 0.55
                 ELSE 0.4
               END AS rank
        FROM code_node n
        WHERE ${filter.where}
          AND (
            lower(n.name) LIKE lower(@pattern)
            OR lower(n.symbol_id) LIKE lower(@pattern)
            OR lower(n.file_path) LIKE lower(@pattern)
          )
        ORDER BY rank DESC, length(n.name), n.file_path
        LIMIT @limit
        `,
      )
      .all({
        ...filter.params,
        query,
        pattern: `%${query}%`,
        startPattern: `${query}%`,
        limit: options.limit,
      }) as Row[];
    return rows.map((row) => ({
      node: nodeFromRow(row),
      score: Number(row.rank) || 0,
      reasons: ["like"],
    }));
  }

  private searchCodeNodesByFilters(
    repoId: string,
    options: { types: string[]; languages: string[]; limit: number },
  ): Array<{ node: CodeGraphNode; score: number; reasons: string[] }> {
    const filter = nodeFilterSql(repoId, options.types, options.languages);
    const rows = this.db
      .prepare(
        `
        SELECT n.id, n.repo_id, n.type, n.name, n.file_path, n.start_line, n.end_line,
               n.language, n.symbol_id, n.summary, n.hash, n.metadata_json
        FROM code_node n
        WHERE ${filter.where}
        ORDER BY n.type, n.file_path, n.start_line, n.name
        LIMIT @limit
        `,
      )
      .all({ ...filter.params, limit: options.limit }) as Row[];
    return rows.map((row) => ({
      node: nodeFromRow(row),
      score: 0.5,
      reasons: ["filter"],
    }));
  }

  private searchCodeChunksLike(
    repoId: string,
    query: string,
    limit: number,
  ): Array<{ chunk: CodeChunk; score: number; match_type: string }> {
    const pattern = `%${query.trim().replace(/^"+|"+$/g, "")}%`;
    const rows = this.db
      .prepare(
        `
        SELECT id, repo_id, node_id, file_path, start_line, end_line,
               content, content_hash, token_count,
               CASE
                 WHEN lower(file_path) LIKE lower(@pattern) THEN 0.8
                 ELSE 0.5
               END AS rank
        FROM code_chunk
        WHERE repo_id = @repoId
          AND (
            lower(content) LIKE lower(@pattern)
            OR lower(file_path) LIKE lower(@pattern)
          )
        ORDER BY rank DESC, file_path, start_line
        LIMIT @limit
        `,
      )
      .all({ repoId, pattern, limit }) as Row[];
    return rows.map((row) => ({
      chunk: chunkFromRow(row),
      score: Number(row.rank) || 0,
      match_type: "like",
    }));
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

function nodeFilterSql(
  repoId: string,
  types: string[],
  languages: string[],
): { where: string; params: Record<string, string> } {
  const params: Record<string, string> = { repoId };
  const clauses = ["n.repo_id = @repoId"];
  if (types.length) {
    const names = types.map((nodeType, index) => {
      const key = `type${index}`;
      params[key] = nodeType;
      return `@${key}`;
    });
    clauses.push(`n.type IN (${names.join(", ")})`);
  }
  if (languages.length) {
    const names = languages.map((language, index) => {
      const key = `language${index}`;
      params[key] = language;
      return `@${key}`;
    });
    clauses.push(`n.language IN (${names.join(", ")})`);
  }
  return { where: clauses.join(" AND "), params };
}

function nodeFtsQuery(query: string): string {
  return terms(query)
    .map((term) => `"${term}"*`)
    .join(" OR ");
}

function chunkFtsQuery(query: string): string {
  return terms(query)
    .map((term) => `"${term}"`)
    .join(" OR ");
}

function terms(value: string): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const match of value.matchAll(TOKEN_RE)) {
    const term = match[0].toLowerCase();
    if (seen.has(term)) {
      continue;
    }
    seen.add(term);
    result.push(term);
    if (result.length >= 16) {
      break;
    }
  }
  return result;
}

function scoreNodeHit(
  node: CodeGraphNode,
  query: string,
  baseScore: number,
): number {
  if (!query) {
    return baseScore;
  }
  const queryLower = query.toLowerCase();
  const queryTerms = [...queryLower.matchAll(TOKEN_RE)].map(
    (match) => match[0],
  );
  const nameLower = node.name.toLowerCase();
  let score = baseScore;
  if (
    nameLower === queryLower.replace(/\s+/g, "") ||
    nameLower === queryLower
  ) {
    score += 2;
  } else if (queryTerms.some((term) => term === nameLower)) {
    score += 1.4;
  } else if (nameLower.startsWith(queryLower)) {
    score += 0.9;
  } else if (nameLower.includes(queryLower)) {
    score += 0.6;
  }
  if (
    node.file_path &&
    queryTerms.some((term) => node.file_path.toLowerCase().includes(term))
  ) {
    score += 0.25;
  }
  score +=
    {
      endpoint: 0.35,
      function: 0.3,
      method: 0.3,
      class: 0.28,
      interface: 0.25,
      schema: 0.22,
      file: 0.1,
      module: -0.15,
    }[node.type] ?? 0;
  return Math.round(score * 10_000) / 10_000;
}

function boundedLimit(
  value: number | undefined,
  fallback: number,
  max: number,
): number {
  return typeof value === "number" && Number.isInteger(value) && value > 0
    ? Math.min(value, max)
    : fallback;
}
