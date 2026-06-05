import Database from "better-sqlite3";
import { AnalysisRunRepository } from "./analysisRunRepository.js";
import {
  CodeChunkEmbeddingRepository,
  type CodeChunkEmbeddingSearchOptions,
} from "./embeddingRepository.js";
import { GraphRepository, type GraphSearchFilters } from "./graphRepository.js";
import {
  LlmRunRepository,
  type CachedLlmRunQuery,
  type ListLlmRunsOptions,
  type RecordLlmRunInput,
} from "./llmRunRepository.js";
import { RepoRepository } from "./repoRepository.js";
import { RetrievalTraceRepository } from "./retrievalTraceRepository.js";
import { ensureSchema } from "./schema.js";
import { WikiRepository } from "./wikiRepository.js";
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

export class CodeWikiStore {
  readonly db: Database.Database;
  private readonly analysisRunRepository: AnalysisRunRepository;
  private readonly embeddingRepository: CodeChunkEmbeddingRepository;
  private readonly graphRepository: GraphRepository;
  private readonly llmRunRepository: LlmRunRepository;
  private readonly repoRepository: RepoRepository;
  private readonly retrievalTraceRepository: RetrievalTraceRepository;
  private readonly wikiRepository: WikiRepository;

  constructor(readonly databasePath: string) {
    this.db = new Database(databasePath);
    this.db.pragma("foreign_keys = ON");
    this.db.pragma("journal_mode = WAL");
    this.db.pragma("synchronous = NORMAL");
    this.db.pragma("busy_timeout = 30000");
    this.ensureSchema();
    this.analysisRunRepository = new AnalysisRunRepository(this.db);
    this.embeddingRepository = new CodeChunkEmbeddingRepository(this.db);
    this.graphRepository = new GraphRepository(this.db);
    this.llmRunRepository = new LlmRunRepository(this.db);
    this.repoRepository = new RepoRepository(this.db);
    this.retrievalTraceRepository = new RetrievalTraceRepository(this.db);
    this.wikiRepository = new WikiRepository(this.db);
  }

  close(): void {
    this.db.close();
  }

  ensureSchema(): void {
    ensureSchema(this.db);
  }

  upsertRepo(repo: RepoDescriptor): RepoDescriptor {
    return this.repoRepository.upsertRepo(repo);
  }

  getRepo(repoId: string): RepoDescriptor | null {
    return this.repoRepository.getRepo(repoId);
  }

  listRepos(): RepoDescriptor[] {
    return this.repoRepository.listRepos();
  }

  deleteRepo(repoId: string): boolean {
    return this.repoRepository.deleteRepo(repoId);
  }

  createAnalysisRun(repoId: string): AnalysisRun {
    return this.analysisRunRepository.createAnalysisRun(repoId);
  }

  finishAnalysisRun(
    runId: string,
    options: { status: string; stats: JsonObject; error?: string | null },
  ): AnalysisRun {
    return this.analysisRunRepository.finishAnalysisRun(runId, options);
  }

  updateAnalysisRunStats(runId: string, stats: JsonObject): void {
    this.analysisRunRepository.updateAnalysisRunStats(runId, stats);
  }

  listAnalysisRuns(repoId: string): AnalysisRun[] {
    return this.analysisRunRepository.listAnalysisRuns(repoId);
  }

  getAnalysisRun(runId: string): AnalysisRun | null {
    return this.analysisRunRepository.getAnalysisRun(runId);
  }

  replaceGraph(
    repoId: string,
    options: {
      nodes: CodeGraphNode[];
      edges: CodeGraphEdge[];
      chunks?: CodeChunk[];
    },
  ): void {
    this.graphRepository.replaceGraph(repoId, options);
  }

  getGraph(repoId: string): { nodes: CodeGraphNode[]; edges: CodeGraphEdge[] } {
    return this.graphRepository.getGraph(repoId);
  }

  searchCodeNodes(
    repoId: string,
    query: string,
    filters: GraphSearchFilters = {},
  ): Array<{ node: CodeGraphNode; score: number; reasons: string[] }> {
    return this.graphRepository.searchCodeNodes(repoId, query, filters);
  }

  replaceGraphCommunities(repoId: string, communities: GraphCommunity[]): void {
    this.graphRepository.replaceGraphCommunities(repoId, communities);
  }

  replaceGraphCommunityEdges(
    repoId: string,
    edges: GraphCommunityEdge[],
  ): void {
    this.graphRepository.replaceGraphCommunityEdges(repoId, edges);
  }

  listGraphCommunities(repoId: string): GraphCommunity[] {
    return this.graphRepository.listGraphCommunities(repoId);
  }

  listGraphCommunityEdges(repoId: string): GraphCommunityEdge[] {
    return this.graphRepository.listGraphCommunityEdges(repoId);
  }

  replaceCodeChunks(repoId: string, chunks: CodeChunk[]): void {
    this.graphRepository.replaceCodeChunks(repoId, chunks);
  }

  listCodeChunks(repoId: string): CodeChunk[] {
    return this.graphRepository.listCodeChunks(repoId);
  }

  searchCodeChunks(
    repoId: string,
    query: string,
    limit = 10,
  ): Array<{ chunk: CodeChunk; score: number; match_type: string }> {
    return this.graphRepository.searchCodeChunks(repoId, query, limit);
  }

  replaceCodeChunkEmbeddings(
    repoId: string,
    options: { model: string; embeddings: CodeChunkEmbedding[] },
  ): void {
    this.embeddingRepository.replaceCodeChunkEmbeddings(repoId, options);
  }

  listCodeChunkEmbeddings(
    repoId: string,
    options: { model?: string | undefined } = {},
  ): CodeChunkEmbedding[] {
    return this.embeddingRepository.listCodeChunkEmbeddings(repoId, options);
  }

  searchCodeChunkEmbeddings(
    repoId: string,
    options: CodeChunkEmbeddingSearchOptions,
  ): Array<{ chunk: CodeChunk; score: number; match_type: string }> {
    return this.embeddingRepository.searchCodeChunkEmbeddings(repoId, options);
  }

  saveRetrievalTrace(trace: RetrievalTrace): RetrievalTrace {
    return this.retrievalTraceRepository.saveRetrievalTrace(trace);
  }

  getRetrievalTrace(repoId: string, traceId: string): RetrievalTrace | null {
    return this.retrievalTraceRepository.getRetrievalTrace(repoId, traceId);
  }

  saveDocCatalog(
    repoId: string,
    options: {
      title: string;
      structure: JsonObject;
      language_code?: string;
      catalog_id?: string;
    },
  ): DocCatalog {
    return this.wikiRepository.saveDocCatalog(repoId, options);
  }

  getLatestDocCatalog(repoId: string, languageCode = "en"): DocCatalog | null {
    return this.wikiRepository.getLatestDocCatalog(repoId, languageCode);
  }

  upsertDocPage(page: DocPage): DocPage {
    return this.wikiRepository.upsertDocPage(page);
  }

  getDocPage(
    repoId: string,
    slug: string,
    languageCode = "en",
  ): DocPage | null {
    return this.wikiRepository.getDocPage(repoId, slug, languageCode);
  }

  listDocPages(repoId: string, languageCode = "en"): DocPage[] {
    return this.wikiRepository.listDocPages(repoId, languageCode);
  }

  recordLlmRun(repoId: string, input: RecordLlmRunInput): LlmRun {
    return this.llmRunRepository.recordLlmRun(repoId, input);
  }

  getCachedLlmRun(repoId: string, query: CachedLlmRunQuery): LlmRun | null {
    return this.llmRunRepository.getCachedLlmRun(repoId, query);
  }

  updateLlmRunStatus(
    runId: string,
    options: { status: string; error?: string | null | undefined },
  ): LlmRun | null {
    return this.llmRunRepository.updateLlmRunStatus(runId, options);
  }

  listLlmRuns(repoId: string, options: ListLlmRunsOptions = {}): LlmRun[] {
    return this.llmRunRepository.listLlmRuns(repoId, options);
  }
}
