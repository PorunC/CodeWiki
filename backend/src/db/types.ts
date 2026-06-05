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
import type {
  CachedLlmRunQuery,
  ListLlmRunsOptions,
  RecordLlmRunInput,
} from "./llmRunRepository.js";

export type MaybePromise<T> = T | Promise<T>;

export type CodeWikiStoreApi = {
  close(): MaybePromise<void>;
  ensureSchema(): MaybePromise<void>;
  upsertRepo(repo: RepoDescriptor): MaybePromise<RepoDescriptor>;
  getRepo(repoId: string): MaybePromise<RepoDescriptor | null>;
  listRepos(): MaybePromise<RepoDescriptor[]>;
  deleteRepo(repoId: string): MaybePromise<boolean>;
  createAnalysisRun(repoId: string): MaybePromise<AnalysisRun>;
  finishAnalysisRun(
    runId: string,
    options: { status: string; stats: JsonObject; error?: string | null },
  ): MaybePromise<AnalysisRun>;
  updateAnalysisRunStats(
    runId: string,
    stats: JsonObject,
  ): MaybePromise<void>;
  listAnalysisRuns(repoId: string): MaybePromise<AnalysisRun[]>;
  getAnalysisRun(runId: string): MaybePromise<AnalysisRun | null>;
  replaceGraph(
    repoId: string,
    options: {
      nodes: CodeGraphNode[];
      edges: CodeGraphEdge[];
      chunks?: CodeChunk[];
    },
  ): MaybePromise<void>;
  getGraph(
    repoId: string,
  ): MaybePromise<{ nodes: CodeGraphNode[]; edges: CodeGraphEdge[] }>;
  searchCodeNodes(
    repoId: string,
    query: string,
    filters?: GraphSearchFilters,
  ): MaybePromise<Array<{ node: CodeGraphNode; score: number; reasons: string[] }>>;
  replaceGraphCommunities(
    repoId: string,
    communities: GraphCommunity[],
  ): MaybePromise<void>;
  replaceGraphCommunityEdges(
    repoId: string,
    edges: GraphCommunityEdge[],
  ): MaybePromise<void>;
  listGraphCommunities(repoId: string): MaybePromise<GraphCommunity[]>;
  listGraphCommunityEdges(repoId: string): MaybePromise<GraphCommunityEdge[]>;
  replaceCodeChunks(repoId: string, chunks: CodeChunk[]): MaybePromise<void>;
  listCodeChunks(repoId: string): MaybePromise<CodeChunk[]>;
  searchCodeChunks(
    repoId: string,
    query: string,
    limit?: number,
  ): MaybePromise<Array<{ chunk: CodeChunk; score: number; match_type: string }>>;
  replaceCodeChunkEmbeddings(
    repoId: string,
    options: { model: string; embeddings: CodeChunkEmbedding[] },
  ): MaybePromise<void>;
  listCodeChunkEmbeddings(
    repoId: string,
    options?: { model?: string | undefined },
  ): MaybePromise<CodeChunkEmbedding[]>;
  searchCodeChunkEmbeddings(
    repoId: string,
    options: CodeChunkEmbeddingSearchOptions,
  ): MaybePromise<Array<{ chunk: CodeChunk; score: number; match_type: string }>>;
  saveRetrievalTrace(trace: RetrievalTrace): MaybePromise<RetrievalTrace>;
  getRetrievalTrace(
    repoId: string,
    traceId: string,
  ): MaybePromise<RetrievalTrace | null>;
  saveDocCatalog(
    repoId: string,
    options: {
      title: string;
      structure: JsonObject;
      language_code?: string;
      catalog_id?: string;
    },
  ): MaybePromise<DocCatalog>;
  getLatestDocCatalog(
    repoId: string,
    languageCode?: string,
  ): MaybePromise<DocCatalog | null>;
  upsertDocPage(page: DocPage): MaybePromise<DocPage>;
  getDocPage(
    repoId: string,
    slug: string,
    languageCode?: string,
  ): MaybePromise<DocPage | null>;
  listDocPages(repoId: string, languageCode?: string): MaybePromise<DocPage[]>;
  recordLlmRun(
    repoId: string,
    input: RecordLlmRunInput,
  ): MaybePromise<LlmRun>;
  getCachedLlmRun(
    repoId: string,
    query: CachedLlmRunQuery,
  ): MaybePromise<LlmRun | null>;
  updateLlmRunStatus(
    runId: string,
    options: { status: string; error?: string | null | undefined },
  ): MaybePromise<LlmRun | null>;
  listLlmRuns(
    repoId: string,
    options?: ListLlmRunsOptions,
  ): MaybePromise<LlmRun[]>;
};
