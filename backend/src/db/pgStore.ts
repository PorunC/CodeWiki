import { randomUUID } from "node:crypto";
import pg from "pg";
import type {
  AnalysisRun,
  CodeChunk,
  CodeChunkEmbedding,
  CodeGraphEdge,
  CodeGraphNode,
  DocCatalog,
  DocPage,
  GraphCommunity,
  GraphCommunityEdge,
  JsonObject,
  LlmRun,
  RepoDescriptor,
  RetrievalTrace,
} from "../types.js";
import type { CodeChunkEmbeddingSearchOptions } from "./embeddingRepository.js";
import type { GraphSearchFilters } from "./graphRepository.js";
import {
  analysisRunFromRow,
  catalogFromRow,
  chunkFromRow,
  communityEdgeFromRow,
  communityFromRow,
  edgeFromRow,
  embeddingFromRow,
  isoNow,
  llmRunFromRow,
  nodeFromRow,
  normalizeLanguage,
  pageFromRow,
  repoFromRow,
  retrievalTraceFromRow,
  scoreNode,
  stringifyJson,
  type Row,
} from "./mappers.js";
import type {
  CachedLlmRunQuery,
  ListLlmRunsOptions,
  RecordLlmRunInput,
} from "./llmRunRepository.js";
import type { CodeWikiStoreApi } from "./types.js";

const { Pool } = pg;

type PgClient = pg.PoolClient;

type ColumnPatch = {
  table: string;
  column: string;
  ddl: string;
};

const COLUMN_PATCHES: ColumnPatch[] = [
  { table: "repo", column: "git_url", ddl: "git_url TEXT" },
  { table: "repo", column: "commit_hash", ddl: "commit_hash TEXT" },
  {
    table: "llm_run",
    column: "response_content",
    ddl: "response_content TEXT NOT NULL DEFAULT ''",
  },
  {
    table: "llm_run",
    column: "response_usage_json",
    ddl: "response_usage_json TEXT NOT NULL DEFAULT '{}'",
  },
  {
    table: "doc_catalog",
    column: "language_code",
    ddl: "language_code TEXT NOT NULL DEFAULT 'en'",
  },
  {
    table: "doc_page",
    column: "language_code",
    ddl: "language_code TEXT NOT NULL DEFAULT 'en'",
  },
  { table: "graph_community", column: "parent_id", ddl: "parent_id TEXT" },
  {
    table: "graph_community",
    column: "rank",
    ddl: "rank INTEGER NOT NULL DEFAULT 0",
  },
  {
    table: "code_chunk_embedding",
    column: "embedding_json",
    ddl: "embedding_json TEXT NOT NULL DEFAULT '[]'",
  },
];

export class PgCodeWikiStore implements CodeWikiStoreApi {
  readonly databaseUrl: string;
  private readonly pool: pg.Pool;
  private readonly ready: Promise<void>;

  constructor(databaseUrl: string) {
    this.databaseUrl = databaseUrl;
    this.pool = new Pool({ connectionString: databaseUrl });
    this.ready = this.ensureSchema();
  }

  async close(): Promise<void> {
    await this.ready;
    await this.pool.end();
  }

  async ensureSchema(): Promise<void> {
    await this.pool.query(PG_SCHEMA_SQL);
    for (const patch of COLUMN_PATCHES) {
      await this.pool.query(
        `ALTER TABLE ${patch.table} ADD COLUMN IF NOT EXISTS ${patch.ddl}`,
      );
    }
    await this.pool.query(PG_INDEX_SQL);
  }

  async upsertRepo(repo: RepoDescriptor): Promise<RepoDescriptor> {
    await this.ready;
    const now = isoNow();
    const existing = await this.getRepo(repo.id);
    await this.pool.query(
      `
      INSERT INTO repo (
        id, name, path, source_type, git_url, commit_hash, created_at, updated_at
      )
      VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
      ON CONFLICT(id) DO UPDATE SET
        name = EXCLUDED.name,
        path = EXCLUDED.path,
        source_type = EXCLUDED.source_type,
        git_url = EXCLUDED.git_url,
        commit_hash = EXCLUDED.commit_hash,
        updated_at = EXCLUDED.updated_at
      `,
      [
        repo.id,
        repo.name,
        repo.path,
        repo.source_type,
        repo.git_url,
        repo.commit_hash,
        repo.created_at ?? existing?.created_at ?? now,
        now,
      ],
    );
    return (await this.getRepo(repo.id)) ?? { ...repo, created_at: now, updated_at: now };
  }

  async getRepo(repoId: string): Promise<RepoDescriptor | null> {
    await this.ready;
    const result = await this.pool.query("SELECT * FROM repo WHERE id = $1", [
      repoId,
    ]);
    return result.rows[0] ? repoFromRow(result.rows[0] as Row) : null;
  }

  async listRepos(): Promise<RepoDescriptor[]> {
    await this.ready;
    const result = await this.pool.query(
      "SELECT * FROM repo ORDER BY updated_at DESC NULLS LAST, name ASC",
    );
    return result.rows.map((row) => repoFromRow(row as Row));
  }

  async deleteRepo(repoId: string): Promise<boolean> {
    await this.ready;
    const result = await this.pool.query("DELETE FROM repo WHERE id = $1", [
      repoId,
    ]);
    return (result.rowCount ?? 0) > 0;
  }

  async createAnalysisRun(repoId: string): Promise<AnalysisRun> {
    await this.ready;
    const run: AnalysisRun = {
      id: randomUUID(),
      repo_id: repoId,
      status: "running",
      started_at: isoNow(),
      finished_at: null,
      error: null,
      stats: {},
    };
    await this.pool.query(
      `
      INSERT INTO analysis_run (id, repo_id, status, started_at, finished_at, error, stats_json)
      VALUES ($1, $2, $3, $4, $5, $6, $7)
      `,
      [
        run.id,
        run.repo_id,
        run.status,
        run.started_at,
        run.finished_at,
        run.error,
        stringifyJson(run.stats),
      ],
    );
    return run;
  }

  async finishAnalysisRun(
    runId: string,
    options: { status: string; stats: JsonObject; error?: string | null },
  ): Promise<AnalysisRun> {
    await this.ready;
    await this.pool.query(
      `
      UPDATE analysis_run
      SET status = $1, finished_at = $2, error = $3, stats_json = $4
      WHERE id = $5
      `,
      [
        options.status,
        isoNow(),
        options.error ?? null,
        stringifyJson(options.stats),
        runId,
      ],
    );
    const run = await this.getAnalysisRun(runId);
    if (!run) {
      throw new Error(`Analysis run not found: ${runId}`);
    }
    return run;
  }

  async updateAnalysisRunStats(
    runId: string,
    stats: JsonObject,
  ): Promise<void> {
    await this.ready;
    await this.pool.query(
      "UPDATE analysis_run SET stats_json = $1 WHERE id = $2",
      [stringifyJson(stats), runId],
    );
  }

  async listAnalysisRuns(repoId: string): Promise<AnalysisRun[]> {
    await this.ready;
    const result = await this.pool.query(
      "SELECT * FROM analysis_run WHERE repo_id = $1 ORDER BY started_at DESC NULLS LAST",
      [repoId],
    );
    return result.rows.map((row) => analysisRunFromRow(row as Row));
  }

  async getAnalysisRun(runId: string): Promise<AnalysisRun | null> {
    await this.ready;
    const result = await this.pool.query(
      "SELECT * FROM analysis_run WHERE id = $1",
      [runId],
    );
    return result.rows[0] ? analysisRunFromRow(result.rows[0] as Row) : null;
  }

  async replaceGraph(
    repoId: string,
    options: {
      nodes: CodeGraphNode[];
      edges: CodeGraphEdge[];
      chunks?: CodeChunk[];
    },
  ): Promise<void> {
    await this.ready;
    await this.transaction(async (client) => {
      await client.query("DELETE FROM code_edge WHERE repo_id = $1", [repoId]);
      await client.query("DELETE FROM code_node WHERE repo_id = $1", [repoId]);
      for (const node of options.nodes) {
        await client.query(
          `
          INSERT INTO code_node (
            id, repo_id, type, name, file_path, start_line, end_line, language,
            symbol_id, summary, hash, metadata_json
          )
          VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
          `,
          [
            node.id,
            node.repo_id,
            node.type,
            node.name,
            node.file_path,
            node.start_line,
            node.end_line,
            node.language,
            node.symbol_id,
            node.summary,
            node.hash,
            stringifyJson(node.metadata),
          ],
        );
      }
      for (const edge of options.edges) {
        await client.query(
          `
          INSERT INTO code_edge (
            id, repo_id, source_id, target_id, type, confidence, weight,
            is_inferred, metadata_json
          )
          VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
          `,
          [
            edge.id,
            edge.repo_id,
            edge.source_id,
            edge.target_id,
            edge.type,
            edge.confidence,
            edge.weight,
            edge.is_inferred,
            stringifyJson(edge.metadata),
          ],
        );
      }
      if (options.chunks) {
        await this.replaceCodeChunksWithClient(client, repoId, options.chunks);
      }
    });
  }

  async getGraph(
    repoId: string,
  ): Promise<{ nodes: CodeGraphNode[]; edges: CodeGraphEdge[] }> {
    await this.ready;
    const [nodes, edges] = await Promise.all([
      this.pool.query(
        "SELECT * FROM code_node WHERE repo_id = $1 ORDER BY file_path, start_line NULLS LAST",
        [repoId],
      ),
      this.pool.query(
        "SELECT * FROM code_edge WHERE repo_id = $1 ORDER BY type, source_id",
        [repoId],
      ),
    ]);
    return {
      nodes: nodes.rows.map((row) => nodeFromRow(row as Row)),
      edges: edges.rows.map((row) => edgeFromRow(row as Row)),
    };
  }

  async searchCodeNodes(
    repoId: string,
    query: string,
    filters: GraphSearchFilters = {},
  ): Promise<Array<{ node: CodeGraphNode; score: number; reasons: string[] }>> {
    const allNodes = (await this.getGraph(repoId)).nodes;
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

  async replaceGraphCommunities(
    repoId: string,
    communities: GraphCommunity[],
  ): Promise<void> {
    await this.ready;
    await this.transaction(async (client) => {
      await client.query("DELETE FROM graph_community_edge WHERE repo_id = $1", [
        repoId,
      ]);
      await client.query("DELETE FROM graph_community WHERE repo_id = $1", [
        repoId,
      ]);
      for (const community of communities) {
        await client.query(
          `
          INSERT INTO graph_community (
            id, repo_id, name, level, parent_id, rank, node_ids_json,
            summary, summary_hash, created_at
          )
          VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
          `,
          [
            community.id,
            community.repo_id,
            community.name,
            community.level,
            community.parent_id,
            community.rank,
            stringifyJson(community.node_ids),
            community.summary,
            community.summary_hash,
            community.created_at,
          ],
        );
      }
    });
  }

  async replaceGraphCommunityEdges(
    repoId: string,
    edges: GraphCommunityEdge[],
  ): Promise<void> {
    await this.ready;
    await this.transaction(async (client) => {
      await client.query("DELETE FROM graph_community_edge WHERE repo_id = $1", [
        repoId,
      ]);
      for (const edge of edges) {
        await client.query(
          `
          INSERT INTO graph_community_edge (
            id, repo_id, source_community_id, target_community_id, type, weight,
            confidence, reason, evidence_edge_ids_json, created_at
          )
          VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
          `,
          [
            edge.id,
            edge.repo_id,
            edge.source_community_id,
            edge.target_community_id,
            edge.type,
            edge.weight,
            edge.confidence,
            edge.reason,
            stringifyJson(edge.evidence_edge_ids),
            edge.created_at,
          ],
        );
      }
    });
  }

  async listGraphCommunities(repoId: string): Promise<GraphCommunity[]> {
    await this.ready;
    const result = await this.pool.query(
      "SELECT * FROM graph_community WHERE repo_id = $1 ORDER BY level, rank, name",
      [repoId],
    );
    return result.rows.map((row) => communityFromRow(row as Row));
  }

  async listGraphCommunityEdges(repoId: string): Promise<GraphCommunityEdge[]> {
    await this.ready;
    const result = await this.pool.query(
      "SELECT * FROM graph_community_edge WHERE repo_id = $1 ORDER BY type, source_community_id",
      [repoId],
    );
    return result.rows.map((row) => communityEdgeFromRow(row as Row));
  }

  async replaceCodeChunks(repoId: string, chunks: CodeChunk[]): Promise<void> {
    await this.ready;
    await this.transaction((client) =>
      this.replaceCodeChunksWithClient(client, repoId, chunks),
    );
  }

  async listCodeChunks(repoId: string): Promise<CodeChunk[]> {
    await this.ready;
    const result = await this.pool.query(
      "SELECT * FROM code_chunk WHERE repo_id = $1 ORDER BY file_path, start_line",
      [repoId],
    );
    return result.rows.map((row) => chunkFromRow(row as Row));
  }

  async searchCodeChunks(
    repoId: string,
    query: string,
    limit = 10,
  ): Promise<Array<{ chunk: CodeChunk; score: number; match_type: string }>> {
    const normalized = query.trim().toLowerCase();
    const chunks = await this.listCodeChunks(repoId);
    if (!normalized) {
      return chunks
        .slice(0, limit)
        .map((chunk) => ({ chunk, score: 0.1, match_type: "recent" }));
    }
    return chunks
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

  async replaceCodeChunkEmbeddings(
    repoId: string,
    options: { model: string; embeddings: CodeChunkEmbedding[] },
  ): Promise<void> {
    await this.ready;
    await this.transaction(async (client) => {
      await client.query(
        "DELETE FROM code_chunk_embedding WHERE repo_id = $1 AND model = $2",
        [repoId, options.model],
      );
      for (const embedding of options.embeddings) {
        await client.query(
          `
          INSERT INTO code_chunk_embedding (
            id, repo_id, chunk_id, model, dimensions, embedding_json,
            content_hash, created_at
          )
          VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
          `,
          [
            embedding.id,
            embedding.repo_id,
            embedding.chunk_id,
            embedding.model,
            embedding.dimensions,
            stringifyJson(embedding.embedding),
            embedding.content_hash,
            embedding.created_at,
          ],
        );
      }
    });
  }

  async listCodeChunkEmbeddings(
    repoId: string,
    options: { model?: string | undefined } = {},
  ): Promise<CodeChunkEmbedding[]> {
    await this.ready;
    const result = options.model
      ? await this.pool.query(
          `
          SELECT * FROM code_chunk_embedding
          WHERE repo_id = $1 AND model = $2
          ORDER BY created_at DESC NULLS LAST, chunk_id
          `,
          [repoId, options.model],
        )
      : await this.pool.query(
          `
          SELECT * FROM code_chunk_embedding
          WHERE repo_id = $1
          ORDER BY created_at DESC NULLS LAST, model, chunk_id
          `,
          [repoId],
        );
    return result.rows.map((row) => embeddingFromRow(row as Row));
  }

  async searchCodeChunkEmbeddings(
    repoId: string,
    options: CodeChunkEmbeddingSearchOptions,
  ): Promise<Array<{ chunk: CodeChunk; score: number; match_type: string }>> {
    const limit = positiveInt(options.limit, 20);
    const queryEmbedding = validVector(options.queryEmbedding);
    if (!queryEmbedding.length) {
      return [];
    }
    const chunks = await this.listCodeChunks(repoId);
    const chunkById = new Map(chunks.map((chunk) => [chunk.id, chunk]));
    const embeddings = await this.listCodeChunkEmbeddings(repoId, {
      model: options.model,
    });
    return embeddings
      .filter((embedding) => embedding.dimensions === queryEmbedding.length)
      .flatMap((embedding) => {
        const chunk = chunkById.get(embedding.chunk_id);
        if (!chunk) {
          return [];
        }
        const score = cosineSimilarity(queryEmbedding, embedding.embedding);
        return score > 0 ? [{ chunk, score, match_type: "vector" }] : [];
      })
      .sort(
        (left, right) =>
          right.score - left.score ||
          left.chunk.file_path.localeCompare(right.chunk.file_path) ||
          left.chunk.start_line - right.chunk.start_line,
      )
      .slice(0, limit);
  }

  async saveRetrievalTrace(trace: RetrievalTrace): Promise<RetrievalTrace> {
    await this.ready;
    const saved = { ...trace, created_at: trace.created_at ?? isoNow() };
    await this.pool.query(
      `
      INSERT INTO graphrag_trace (id, repo_id, query, max_hops, payload_json, created_at)
      VALUES ($1, $2, $3, $4, $5, $6)
      ON CONFLICT(id) DO UPDATE SET
        repo_id = EXCLUDED.repo_id,
        query = EXCLUDED.query,
        max_hops = EXCLUDED.max_hops,
        payload_json = EXCLUDED.payload_json,
        created_at = EXCLUDED.created_at
      `,
      [
        saved.trace_id,
        saved.repo_id,
        saved.query,
        saved.max_hops,
        stringifyJson(saved),
        saved.created_at,
      ],
    );
    return saved;
  }

  async getRetrievalTrace(
    repoId: string,
    traceId: string,
  ): Promise<RetrievalTrace | null> {
    await this.ready;
    const result = await this.pool.query(
      "SELECT * FROM graphrag_trace WHERE repo_id = $1 AND id = $2",
      [repoId, traceId],
    );
    return result.rows[0] ? retrievalTraceFromRow(result.rows[0] as Row) : null;
  }

  async saveDocCatalog(
    repoId: string,
    options: {
      title: string;
      structure: JsonObject;
      language_code?: string;
      catalog_id?: string;
    },
  ): Promise<DocCatalog> {
    await this.ready;
    const catalog: DocCatalog = {
      id: options.catalog_id ?? randomUUID(),
      repo_id: repoId,
      language_code: normalizeLanguage(options.language_code),
      title: options.title,
      structure: options.structure,
      generated_at: isoNow(),
    };
    await this.pool.query(
      `
      INSERT INTO doc_catalog (id, repo_id, language_code, title, structure_json, generated_at)
      VALUES ($1, $2, $3, $4, $5, $6)
      `,
      [
        catalog.id,
        catalog.repo_id,
        catalog.language_code,
        catalog.title,
        stringifyJson(catalog.structure),
        catalog.generated_at,
      ],
    );
    return catalog;
  }

  async getLatestDocCatalog(
    repoId: string,
    languageCode = "en",
  ): Promise<DocCatalog | null> {
    await this.ready;
    const result = await this.pool.query(
      `
      SELECT * FROM doc_catalog
      WHERE repo_id = $1 AND language_code = $2
      ORDER BY generated_at DESC NULLS LAST, id DESC
      LIMIT 1
      `,
      [repoId, normalizeLanguage(languageCode)],
    );
    return result.rows[0] ? catalogFromRow(result.rows[0] as Row) : null;
  }

  async upsertDocPage(page: DocPage): Promise<DocPage> {
    await this.ready;
    const languageCode = normalizeLanguage(page.language_code);
    await this.pool.query(
      `
      INSERT INTO doc_page (
        id, repo_id, language_code, slug, title, parent_slug, markdown,
        source_refs_json, graph_refs_json, status, updated_at
      )
      VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
      ON CONFLICT(repo_id, language_code, slug) DO UPDATE SET
        title = EXCLUDED.title,
        parent_slug = EXCLUDED.parent_slug,
        markdown = EXCLUDED.markdown,
        source_refs_json = EXCLUDED.source_refs_json,
        graph_refs_json = EXCLUDED.graph_refs_json,
        status = EXCLUDED.status,
        updated_at = EXCLUDED.updated_at
      `,
      [
        page.id,
        page.repo_id,
        languageCode,
        page.slug,
        page.title,
        page.parent_slug,
        page.markdown,
        stringifyJson(page.source_refs),
        stringifyJson(page.graph_refs),
        page.status,
        page.updated_at,
      ],
    );
    return (await this.getDocPage(page.repo_id, page.slug, languageCode)) ?? page;
  }

  async getDocPage(
    repoId: string,
    slug: string,
    languageCode = "en",
  ): Promise<DocPage | null> {
    await this.ready;
    const result = await this.pool.query(
      "SELECT * FROM doc_page WHERE repo_id = $1 AND language_code = $2 AND slug = $3",
      [repoId, normalizeLanguage(languageCode), slug],
    );
    return result.rows[0] ? pageFromRow(result.rows[0] as Row) : null;
  }

  async listDocPages(
    repoId: string,
    languageCode = "en",
  ): Promise<DocPage[]> {
    await this.ready;
    const result = await this.pool.query(
      "SELECT * FROM doc_page WHERE repo_id = $1 AND language_code = $2 ORDER BY slug",
      [repoId, normalizeLanguage(languageCode)],
    );
    return result.rows.map((row) => pageFromRow(row as Row));
  }

  async recordLlmRun(
    repoId: string,
    input: RecordLlmRunInput,
  ): Promise<LlmRun> {
    await this.ready;
    const run = {
      id: randomUUID(),
      repo_id: repoId,
      task_type: input.taskType,
      provider: input.provider ?? null,
      model: input.model,
      model_alias: input.modelAlias ?? null,
      prompt_version: input.promptVersion ?? null,
      input_hash: input.inputHash,
      cache_key: input.cacheKey,
      tokens_in: input.tokensIn ?? 0,
      tokens_out: input.tokensOut ?? 0,
      cost_usd: input.costUsd ?? null,
      duration_ms: input.durationMs ?? null,
      response_content: input.responseContent ?? "",
      response_usage: input.responseUsage ?? {},
      cached: input.cached ?? false,
      status: input.status ?? "success",
      error: input.error ?? null,
      created_at: isoNow(),
    } satisfies LlmRun;
    await this.pool.query(
      `
      INSERT INTO llm_run (
        id, repo_id, task_type, provider, model, model_alias, prompt_version,
        input_hash, cache_key, tokens_in, tokens_out, cost_usd, duration_ms,
        response_content, response_usage_json, cached, status, error, created_at
      )
      VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19)
      `,
      [
        run.id,
        run.repo_id,
        run.task_type,
        run.provider,
        run.model,
        run.model_alias,
        run.prompt_version,
        run.input_hash,
        run.cache_key,
        run.tokens_in,
        run.tokens_out,
        run.cost_usd,
        run.duration_ms,
        run.response_content,
        stringifyJson(run.response_usage),
        run.cached,
        run.status,
        run.error,
        run.created_at,
      ],
    );
    return run;
  }

  async getCachedLlmRun(
    repoId: string,
    query: CachedLlmRunQuery,
  ): Promise<LlmRun | null> {
    await this.ready;
    const conditions = [
      "repo_id = $1",
      "task_type = $2",
      "cache_key = $3",
      "input_hash = $4",
      "status = 'success'",
      "response_content != ''",
    ];
    const values: Array<string | null> = [
      repoId,
      query.taskType,
      query.cacheKey,
      query.inputHash,
    ];
    if (query.model) {
      values.push(query.model);
      conditions.push(`model = $${values.length}`);
    }
    if (query.promptVersion) {
      values.push(query.promptVersion);
      conditions.push(`prompt_version = $${values.length}`);
    }
    const result = await this.pool.query(
      `
      SELECT * FROM llm_run
      WHERE ${conditions.join(" AND ")}
      ORDER BY created_at DESC NULLS LAST, id DESC
      LIMIT 1
      `,
      values,
    );
    return result.rows[0] ? llmRunFromRow(result.rows[0] as Row) : null;
  }

  async updateLlmRunStatus(
    runId: string,
    options: { status: string; error?: string | null | undefined },
  ): Promise<LlmRun | null> {
    await this.ready;
    await this.pool.query(
      "UPDATE llm_run SET status = $1, error = $2 WHERE id = $3",
      [options.status, options.error ?? null, runId],
    );
    const result = await this.pool.query("SELECT * FROM llm_run WHERE id = $1", [
      runId,
    ]);
    return result.rows[0] ? llmRunFromRow(result.rows[0] as Row) : null;
  }

  async listLlmRuns(
    repoId: string,
    options: ListLlmRunsOptions = {},
  ): Promise<LlmRun[]> {
    await this.ready;
    const result = options.taskType
      ? await this.pool.query(
          `
          SELECT * FROM llm_run
          WHERE repo_id = $1 AND task_type = $2
          ORDER BY created_at DESC NULLS LAST, id DESC
          `,
          [repoId, options.taskType],
        )
      : await this.pool.query(
          `
          SELECT * FROM llm_run
          WHERE repo_id = $1
          ORDER BY created_at DESC NULLS LAST, id DESC
          `,
          [repoId],
        );
    return result.rows.map((row) => llmRunFromRow(row as Row));
  }

  private async replaceCodeChunksWithClient(
    client: PgClient,
    repoId: string,
    chunks: CodeChunk[],
  ): Promise<void> {
    await client.query("DELETE FROM code_chunk WHERE repo_id = $1", [repoId]);
    for (const chunk of chunks) {
      await client.query(
        `
        INSERT INTO code_chunk (
          id, repo_id, node_id, file_path, start_line, end_line, content,
          content_hash, token_count
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        `,
        [
          chunk.id,
          chunk.repo_id,
          chunk.node_id,
          chunk.file_path,
          chunk.start_line,
          chunk.end_line,
          chunk.content,
          chunk.content_hash,
          chunk.token_count,
        ],
      );
    }
  }

  private async transaction<T>(
    fn: (client: PgClient) => Promise<T>,
  ): Promise<T> {
    const client = await this.pool.connect();
    try {
      await client.query("BEGIN");
      const result = await fn(client);
      await client.query("COMMIT");
      return result;
    } catch (error) {
      await client.query("ROLLBACK");
      throw error;
    } finally {
      client.release();
    }
  }
}

function cosineSimilarity(left: number[], right: number[]): number {
  if (left.length !== right.length || left.length === 0) {
    return 0;
  }
  let dot = 0;
  let leftNorm = 0;
  let rightNorm = 0;
  for (let index = 0; index < left.length; index += 1) {
    const leftValue = left[index] ?? 0;
    const rightValue = right[index] ?? 0;
    dot += leftValue * rightValue;
    leftNorm += leftValue * leftValue;
    rightNorm += rightValue * rightValue;
  }
  if (leftNorm === 0 || rightNorm === 0) {
    return 0;
  }
  return dot / (Math.sqrt(leftNorm) * Math.sqrt(rightNorm));
}

function validVector(values: number[]): number[] {
  return values.filter((value) => Number.isFinite(value));
}

function positiveInt(value: number | undefined, fallback: number): number {
  return typeof value === "number" && Number.isInteger(value) && value > 0
    ? value
    : fallback;
}

const PG_SCHEMA_SQL = `
CREATE TABLE IF NOT EXISTS repo (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  path TEXT NOT NULL,
  source_type TEXT NOT NULL DEFAULT 'local',
  git_url TEXT,
  commit_hash TEXT,
  created_at TEXT,
  updated_at TEXT
);

CREATE TABLE IF NOT EXISTS analysis_run (
  id TEXT PRIMARY KEY,
  repo_id TEXT NOT NULL REFERENCES repo(id) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'pending',
  started_at TEXT,
  finished_at TEXT,
  error TEXT,
  stats_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS llm_run (
  id TEXT PRIMARY KEY,
  repo_id TEXT NOT NULL REFERENCES repo(id) ON DELETE CASCADE,
  task_type TEXT NOT NULL,
  provider TEXT,
  model TEXT NOT NULL,
  model_alias TEXT,
  prompt_version TEXT,
  input_hash TEXT NOT NULL,
  cache_key TEXT NOT NULL,
  tokens_in INTEGER NOT NULL DEFAULT 0,
  tokens_out INTEGER NOT NULL DEFAULT 0,
  cost_usd DOUBLE PRECISION,
  duration_ms INTEGER,
  response_content TEXT NOT NULL DEFAULT '',
  response_usage_json TEXT NOT NULL DEFAULT '{}',
  cached BOOLEAN NOT NULL DEFAULT false,
  status TEXT NOT NULL DEFAULT 'success',
  error TEXT,
  created_at TEXT
);

CREATE TABLE IF NOT EXISTS code_node (
  id TEXT PRIMARY KEY,
  repo_id TEXT NOT NULL REFERENCES repo(id) ON DELETE CASCADE,
  type TEXT NOT NULL,
  name TEXT NOT NULL,
  file_path TEXT NOT NULL DEFAULT '',
  start_line INTEGER,
  end_line INTEGER,
  language TEXT,
  symbol_id TEXT,
  summary TEXT,
  hash TEXT NOT NULL DEFAULT '',
  metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS code_edge (
  id TEXT PRIMARY KEY,
  repo_id TEXT NOT NULL REFERENCES repo(id) ON DELETE CASCADE,
  source_id TEXT NOT NULL REFERENCES code_node(id) ON DELETE CASCADE,
  target_id TEXT NOT NULL REFERENCES code_node(id) ON DELETE CASCADE,
  type TEXT NOT NULL,
  confidence DOUBLE PRECISION NOT NULL DEFAULT 1.0,
  weight DOUBLE PRECISION NOT NULL DEFAULT 1.0,
  is_inferred BOOLEAN NOT NULL DEFAULT false,
  metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS graph_community (
  id TEXT PRIMARY KEY,
  repo_id TEXT NOT NULL REFERENCES repo(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  level INTEGER NOT NULL DEFAULT 0,
  parent_id TEXT,
  rank INTEGER NOT NULL DEFAULT 0,
  node_ids_json TEXT NOT NULL DEFAULT '[]',
  summary TEXT,
  summary_hash TEXT,
  created_at TEXT
);

CREATE TABLE IF NOT EXISTS graph_community_edge (
  id TEXT PRIMARY KEY,
  repo_id TEXT NOT NULL REFERENCES repo(id) ON DELETE CASCADE,
  source_community_id TEXT NOT NULL REFERENCES graph_community(id) ON DELETE CASCADE,
  target_community_id TEXT NOT NULL REFERENCES graph_community(id) ON DELETE CASCADE,
  type TEXT NOT NULL,
  weight DOUBLE PRECISION NOT NULL DEFAULT 1.0,
  confidence DOUBLE PRECISION NOT NULL DEFAULT 1.0,
  reason TEXT,
  evidence_edge_ids_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT
);

CREATE TABLE IF NOT EXISTS code_chunk (
  id TEXT PRIMARY KEY,
  repo_id TEXT NOT NULL REFERENCES repo(id) ON DELETE CASCADE,
  node_id TEXT REFERENCES code_node(id) ON DELETE SET NULL,
  file_path TEXT NOT NULL,
  start_line INTEGER NOT NULL,
  end_line INTEGER NOT NULL,
  content TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  token_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS code_chunk_embedding (
  id TEXT PRIMARY KEY,
  repo_id TEXT NOT NULL REFERENCES repo(id) ON DELETE CASCADE,
  chunk_id TEXT NOT NULL REFERENCES code_chunk(id) ON DELETE CASCADE,
  model TEXT NOT NULL,
  dimensions INTEGER NOT NULL,
  embedding_json TEXT NOT NULL DEFAULT '[]',
  content_hash TEXT NOT NULL,
  created_at TEXT
);

CREATE TABLE IF NOT EXISTS graphrag_trace (
  id TEXT PRIMARY KEY,
  repo_id TEXT NOT NULL REFERENCES repo(id) ON DELETE CASCADE,
  query TEXT NOT NULL,
  max_hops INTEGER NOT NULL DEFAULT 2,
  payload_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT
);

CREATE TABLE IF NOT EXISTS doc_catalog (
  id TEXT PRIMARY KEY,
  repo_id TEXT NOT NULL REFERENCES repo(id) ON DELETE CASCADE,
  language_code TEXT NOT NULL DEFAULT 'en',
  title TEXT NOT NULL,
  structure_json TEXT NOT NULL DEFAULT '{"items":[]}',
  generated_at TEXT
);

CREATE TABLE IF NOT EXISTS doc_page (
  id TEXT PRIMARY KEY,
  repo_id TEXT NOT NULL REFERENCES repo(id) ON DELETE CASCADE,
  language_code TEXT NOT NULL DEFAULT 'en',
  slug TEXT NOT NULL,
  title TEXT NOT NULL,
  parent_slug TEXT,
  markdown TEXT NOT NULL DEFAULT '',
  source_refs_json TEXT NOT NULL DEFAULT '[]',
  graph_refs_json TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'draft',
  updated_at TEXT,
  UNIQUE(repo_id, language_code, slug)
);
`;

const PG_INDEX_SQL = `
CREATE INDEX IF NOT EXISTS idx_analysis_run_repo ON analysis_run(repo_id, started_at);
CREATE INDEX IF NOT EXISTS idx_llm_run_task ON llm_run(repo_id, task_type, cache_key);
CREATE INDEX IF NOT EXISTS idx_llm_run_cache
ON llm_run(repo_id, task_type, cache_key, input_hash, model, prompt_version);
CREATE INDEX IF NOT EXISTS idx_llm_run_created ON llm_run(repo_id, created_at);
CREATE INDEX IF NOT EXISTS idx_code_node_repo ON code_node(repo_id);
CREATE INDEX IF NOT EXISTS idx_code_node_type ON code_node(repo_id, type);
CREATE INDEX IF NOT EXISTS idx_code_node_file ON code_node(repo_id, file_path);
CREATE INDEX IF NOT EXISTS idx_code_edge_repo ON code_edge(repo_id);
CREATE INDEX IF NOT EXISTS idx_code_edge_source ON code_edge(source_id);
CREATE INDEX IF NOT EXISTS idx_code_edge_target ON code_edge(target_id);
CREATE INDEX IF NOT EXISTS idx_graph_community_repo ON graph_community(repo_id);
CREATE INDEX IF NOT EXISTS idx_graph_community_level ON graph_community(repo_id, level);
CREATE INDEX IF NOT EXISTS idx_graph_community_parent ON graph_community(repo_id, parent_id);
CREATE INDEX IF NOT EXISTS idx_graph_community_edge_repo ON graph_community_edge(repo_id);
CREATE INDEX IF NOT EXISTS idx_graph_community_edge_source ON graph_community_edge(source_community_id);
CREATE INDEX IF NOT EXISTS idx_graph_community_edge_target ON graph_community_edge(target_community_id);
CREATE INDEX IF NOT EXISTS idx_graph_community_edge_type ON graph_community_edge(repo_id, type);
CREATE INDEX IF NOT EXISTS idx_code_chunk_repo ON code_chunk(repo_id);
CREATE INDEX IF NOT EXISTS idx_code_chunk_node ON code_chunk(node_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_code_chunk_embedding_chunk_model
ON code_chunk_embedding(repo_id, chunk_id, model);
CREATE INDEX IF NOT EXISTS idx_code_chunk_embedding_repo
ON code_chunk_embedding(repo_id, model);
CREATE INDEX IF NOT EXISTS idx_code_chunk_embedding_hash
ON code_chunk_embedding(repo_id, model, content_hash);
CREATE INDEX IF NOT EXISTS idx_graphrag_trace_repo ON graphrag_trace(repo_id, created_at);
CREATE INDEX IF NOT EXISTS idx_doc_catalog_repo ON doc_catalog(repo_id, language_code, generated_at);
CREATE INDEX IF NOT EXISTS idx_doc_page_repo ON doc_page(repo_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_doc_page_slug_language
ON doc_page(repo_id, language_code, slug);
`;
