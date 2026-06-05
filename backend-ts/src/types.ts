export type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [key: string]: JsonValue };

export type JsonObject = Record<string, JsonValue>;

export type RepoDescriptor = {
  id: string;
  name: string;
  path: string;
  source_type: string;
  git_url: string | null;
  commit_hash: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type RepoFile = {
  path: string;
  absolute_path: string;
  language: string;
  is_source: boolean;
  size_bytes: number;
  modified_at: string;
};

export type ScannedFile = RepoFile & {
  sha256: string;
  last_commit_at?: string | null;
};

export type RepoFileScanResult = {
  repo: RepoDescriptor;
  files: RepoFile[];
  scanned_count: number;
  ignored_count: number;
  skipped_count: number;
};

export type RepoScanResult = {
  repo: RepoDescriptor;
  files: ScannedFile[];
  scanned_count: number;
  ignored_count: number;
  skipped_count: number;
};

export type CodeGraphNode = {
  id: string;
  repo_id: string;
  type: string;
  name: string;
  file_path: string;
  start_line: number | null;
  end_line: number | null;
  language: string | null;
  symbol_id: string | null;
  summary: string | null;
  hash: string;
  metadata: JsonObject;
};

export type CodeGraphEdge = {
  id: string;
  repo_id: string;
  source_id: string;
  target_id: string;
  type: string;
  confidence: number;
  weight: number;
  is_inferred: boolean;
  metadata: JsonObject;
};

export type GraphCommunity = {
  id: string;
  repo_id: string;
  name: string;
  level: number;
  parent_id: string | null;
  rank: number;
  node_ids: string[];
  summary: string | null;
  summary_hash: string | null;
  created_at: string | null;
};

export type GraphCommunityEdge = {
  id: string;
  repo_id: string;
  source_community_id: string;
  target_community_id: string;
  type: string;
  weight: number;
  confidence: number;
  reason: string | null;
  evidence_edge_ids: string[];
  created_at: string | null;
};

export type CodeChunk = {
  id: string;
  repo_id: string;
  node_id: string | null;
  file_path: string;
  start_line: number;
  end_line: number;
  content: string;
  content_hash: string;
  token_count: number;
};

export type CodeChunkEmbedding = {
  id: string;
  repo_id: string;
  chunk_id: string;
  model: string;
  dimensions: number;
  embedding: number[];
  content_hash: string;
  created_at: string | null;
};

export type DocCatalog = {
  id: string;
  repo_id: string;
  language_code: string;
  title: string;
  structure: JsonObject;
  generated_at: string | null;
};

export type DocPage = {
  id: string;
  repo_id: string;
  language_code: string;
  slug: string;
  title: string;
  parent_slug: string | null;
  markdown: string;
  source_refs: JsonObject[];
  graph_refs: string[];
  status: string;
  updated_at: string | null;
};

export type GraphRAGBuildResult = {
  repo_id: string;
  status: string;
  chunk_count: number;
  embedding_count: number;
  embedding_model: string | null;
  include_embeddings: boolean;
};

export type RetrievalTrace = {
  repo_id: string;
  query: string;
  max_hops: number;
  trace_id: string;
  seed_nodes: JsonObject[];
  expanded_nodes: JsonObject[];
  source_chunks: JsonObject[];
  related_edges: JsonObject[];
  community_summaries: JsonObject[];
  community_edges: JsonObject[];
  context_pack: JsonObject;
  chunks: CodeChunk[];
  nodes: JsonObject[];
  edges: JsonObject[];
  communities: JsonObject[];
  context: string;
  created_at: string | null;
};

export type AnalysisRun = {
  id: string;
  repo_id: string;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  stats: JsonObject;
};

export type LlmRun = {
  id: string;
  repo_id: string;
  task_type: string;
  provider: string | null;
  model: string;
  model_alias: string | null;
  prompt_version: string | null;
  input_hash: string;
  cache_key: string;
  tokens_in: number;
  tokens_out: number;
  cost_usd: number | null;
  duration_ms: number | null;
  response_content: string;
  response_usage: JsonObject;
  cached: boolean;
  status: string;
  error: string | null;
  created_at: string | null;
};

export type AnalysisResult = {
  run_id: string;
  repo_id: string;
  status: string;
  scanned_count: number;
  parsed_file_count: number;
  reused_file_count: number;
  node_count: number;
  edge_count: number;
  chunk_count: number;
  community_count: number;
  community_count_by_level: Record<string, number>;
  errors: JsonObject[];
  mode: string;
};

export type IncrementalUpdatePlan = {
  repo_id: string;
  changed_files: string[];
  new_files: string[];
  deleted_files: string[];
  unchanged_files: string[];
  affected_files: string[];
  detection_strategy: string;
  base_commit: string | null;
  head_commit: string | null;
};

export type RepositoryUpdateResult = AnalysisResult & {
  plan: IncrementalUpdatePlan;
  stale_pages: string[];
};
