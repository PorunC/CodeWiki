export type RepoSummary = {
  id: string;
  name: string;
  path: string;
  source_type: string;
  git_url?: string;
  commit_hash?: string;
};

export type RepoFileRecord = {
  path: string;
  language: string;
  is_source: boolean;
  size_bytes: number;
  sha256: string;
  modified_at: string;
};

export type RepoFileTreeNode = {
  type: "directory" | "file";
  name: string;
  path: string;
  language?: string;
  is_source?: boolean;
  size_bytes?: number;
  sha256?: string;
  modified_at?: string;
  children?: RepoFileTreeNode[];
};

export type RepoFilesResponse = {
  repo_id: string;
  root: RepoFileTreeNode;
  files: RepoFileRecord[];
  scanned_count: number;
  ignored_count: number;
  skipped_count: number;
};

export type AnalysisRunResponse = {
  run_id: string;
  repo_id: string;
  status: string;
  scanned_count: number;
  parsed_file_count: number;
  node_count: number;
  edge_count: number;
  community_count: number;
  errors: string[];
  community_naming?: Record<string, unknown>;
};

export type IncrementalUpdateResponse = {
  run_id: string;
  repo_id: string;
  status: string;
  plan: Record<string, unknown>;
  scanned_count: number;
  parsed_file_count: number;
  reused_file_count: number;
  node_count: number;
  edge_count: number;
  community_count: number;
  chunk_count: number;
  stale_pages: string[];
  wiki_regeneration: Record<string, unknown>;
  errors: string[];
  community_naming?: Record<string, unknown>;
};

export type LlmModelsResponse = {
  mode: string;
  base_url: string;
  default_model: string;
  small_model: string;
  large_model: string;
  catalog_model: string;
  community_model: string;
  page_model: string;
  qa_model: string;
  embedding_model: string;
};

export type CodeNode = {
  id: string;
  type: string;
  name: string;
  file_path: string | null;
  start_line: number | null;
  end_line: number | null;
  language: string | null;
  symbol_id: string | null;
  confidence: number;
  provenance: Record<string, unknown>;
  metadata: Record<string, unknown>;
};

export type CodeEdge = {
  id: string;
  source: string;
  target: string;
  type: string;
  confidence: number;
  confidence_level?: string | null;
  is_inferred: boolean;
  provenance: Record<string, unknown>;
  metadata: Record<string, unknown>;
};

export type GraphCommunity = {
  id: string;
  name: string;
  level: number;
  node_ids: string[];
  summary: string;
};

export type GraphResponse = {
  repo_id: string;
  nodes: CodeNode[];
  edges: CodeEdge[];
  communities?: GraphCommunity[];
};

export type SourceRef = {
  citation_id?: string;
  file_path: string;
  start_line: number;
  end_line: number;
  source_url?: string;
};

export type AskResponse = {
  answer: string;
  sources: SourceRef[];
  related_nodes: Array<Record<string, unknown> & { id?: string; name?: string; type?: string }>;
  related_edges: Array<Record<string, unknown> & { id?: string; type?: string; source_id?: string; target_id?: string }>;
  related_communities?: Array<Record<string, unknown> & { id?: string; name?: string }>;
  trace_id: string;
};

export type WikiCatalogItem = {
  title: string;
  slug: string;
  path?: string;
  order?: number;
  kind?: "page" | "category";
  topic?: string;
  source_hints?: string[];
  children?: WikiCatalogItem[];
};

export type WikiCatalog = {
  id: string;
  repo_id: string;
  title: string;
  structure: {
    items: WikiCatalogItem[];
  };
  generated_at: string | null;
};

export type WikiPageRecord = {
  id: string;
  repo_id: string;
  slug: string;
  title: string;
  parent_slug: string | null;
  markdown: string;
  source_refs: SourceRef[];
  graph_refs: string[];
  status: string;
  updated_at: string | null;
};

export type WikiResponse = {
  repo_id: string;
  catalog: WikiCatalog | null;
  items: WikiCatalogItem[];
  pages: WikiPageRecord[];
};

export type WikiPageGenerationResult = WikiPageRecord & {
  validation_errors: string[];
};

export type GenerateWikiPagesResponse = {
  repo_id: string;
  status: string;
  page_count: number;
  pages: WikiPageGenerationResult[];
};
