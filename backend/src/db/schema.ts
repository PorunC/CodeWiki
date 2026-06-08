import type { CodeWikiSqliteDatabase } from "./sqlite.js";

type Row = Record<string, unknown>;

export function ensureSchema(db: CodeWikiSqliteDatabase): void {
  db.exec(SCHEMA_SQL);
  ensureColumn(db, "repo", "git_url", "git_url TEXT");
  ensureColumn(db, "repo", "commit_hash", "commit_hash TEXT");
  ensureColumn(
    db,
    "llm_run",
    "response_content",
    "response_content TEXT NOT NULL DEFAULT ''",
  );
  ensureColumn(
    db,
    "llm_run",
    "response_usage_json",
    "response_usage_json TEXT NOT NULL DEFAULT '{}'",
  );
  ensureColumn(
    db,
    "doc_catalog",
    "language_code",
    "language_code TEXT NOT NULL DEFAULT 'en'",
  );
  ensureColumn(
    db,
    "doc_page",
    "language_code",
    "language_code TEXT NOT NULL DEFAULT 'en'",
  );
  ensureColumn(db, "graph_community", "parent_id", "parent_id TEXT");
  ensureColumn(db, "graph_community", "rank", "rank INTEGER DEFAULT 0");
  ensureColumn(
    db,
    "code_chunk_embedding",
    "embedding_json",
    "embedding_json TEXT NOT NULL DEFAULT '[]'",
  );
}

function ensureColumn(
  db: CodeWikiSqliteDatabase,
  table: string,
  column: string,
  ddl: string,
): void {
  const rows = db.prepare(`PRAGMA table_info(${table})`).all() as Row[];
  if (rows.some((row) => row.name === column)) {
    return;
  }
  db.exec(`ALTER TABLE ${table} ADD COLUMN ${ddl}`);
}

const SCHEMA_SQL = `
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
CREATE INDEX IF NOT EXISTS idx_analysis_run_repo ON analysis_run(repo_id, started_at);

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
  cost_usd REAL,
  duration_ms INTEGER,
  response_content TEXT NOT NULL DEFAULT '',
  response_usage_json TEXT NOT NULL DEFAULT '{}',
  cached INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'success',
  error TEXT,
  created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_llm_run_task ON llm_run(repo_id, task_type, cache_key);
CREATE INDEX IF NOT EXISTS idx_llm_run_cache
ON llm_run(repo_id, task_type, cache_key, input_hash, model, prompt_version);
CREATE INDEX IF NOT EXISTS idx_llm_run_created ON llm_run(repo_id, created_at);

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
CREATE INDEX IF NOT EXISTS idx_code_node_repo ON code_node(repo_id);
CREATE INDEX IF NOT EXISTS idx_code_node_type ON code_node(repo_id, type);
CREATE INDEX IF NOT EXISTS idx_code_node_file ON code_node(repo_id, file_path);

CREATE TABLE IF NOT EXISTS code_edge (
  id TEXT PRIMARY KEY,
  repo_id TEXT NOT NULL REFERENCES repo(id) ON DELETE CASCADE,
  source_id TEXT NOT NULL REFERENCES code_node(id) ON DELETE CASCADE,
  target_id TEXT NOT NULL REFERENCES code_node(id) ON DELETE CASCADE,
  type TEXT NOT NULL,
  confidence REAL NOT NULL DEFAULT 1.0,
  weight REAL NOT NULL DEFAULT 1.0,
  is_inferred INTEGER NOT NULL DEFAULT 0,
  metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_code_edge_repo ON code_edge(repo_id);
CREATE INDEX IF NOT EXISTS idx_code_edge_source ON code_edge(source_id);
CREATE INDEX IF NOT EXISTS idx_code_edge_target ON code_edge(target_id);

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
CREATE INDEX IF NOT EXISTS idx_graph_community_repo ON graph_community(repo_id);
CREATE INDEX IF NOT EXISTS idx_graph_community_level ON graph_community(repo_id, level);
CREATE INDEX IF NOT EXISTS idx_graph_community_parent ON graph_community(repo_id, parent_id);

CREATE TABLE IF NOT EXISTS graph_community_edge (
  id TEXT PRIMARY KEY,
  repo_id TEXT NOT NULL REFERENCES repo(id) ON DELETE CASCADE,
  source_community_id TEXT NOT NULL REFERENCES graph_community(id) ON DELETE CASCADE,
  target_community_id TEXT NOT NULL REFERENCES graph_community(id) ON DELETE CASCADE,
  type TEXT NOT NULL,
  weight REAL NOT NULL DEFAULT 1.0,
  confidence REAL NOT NULL DEFAULT 1.0,
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
CREATE INDEX IF NOT EXISTS idx_code_chunk_repo ON code_chunk(repo_id);
CREATE INDEX IF NOT EXISTS idx_code_chunk_node ON code_chunk(node_id);

CREATE TABLE IF NOT EXISTS code_chunk_embedding (
  id TEXT PRIMARY KEY,
  repo_id TEXT NOT NULL REFERENCES repo(id) ON DELETE CASCADE,
  chunk_id TEXT NOT NULL REFERENCES code_chunk(id) ON DELETE CASCADE,
  model TEXT NOT NULL,
  dimensions INTEGER NOT NULL,
  embedding_json TEXT NOT NULL DEFAULT '[]',
  content_hash TEXT NOT NULL,
  created_at TEXT,
  UNIQUE(repo_id, chunk_id, model)
);
CREATE INDEX IF NOT EXISTS idx_code_chunk_embedding_repo
ON code_chunk_embedding(repo_id, model);
CREATE INDEX IF NOT EXISTS idx_code_chunk_embedding_hash
ON code_chunk_embedding(repo_id, model, content_hash);

CREATE TABLE IF NOT EXISTS graphrag_trace (
  id TEXT PRIMARY KEY,
  repo_id TEXT NOT NULL REFERENCES repo(id) ON DELETE CASCADE,
  query TEXT NOT NULL,
  max_hops INTEGER NOT NULL DEFAULT 2,
  payload_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_graphrag_trace_repo ON graphrag_trace(repo_id, created_at);

CREATE TABLE IF NOT EXISTS doc_catalog (
  id TEXT PRIMARY KEY,
  repo_id TEXT NOT NULL REFERENCES repo(id) ON DELETE CASCADE,
  language_code TEXT NOT NULL DEFAULT 'en',
  title TEXT NOT NULL,
  structure_json TEXT NOT NULL DEFAULT '{"items":[]}',
  generated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_doc_catalog_repo ON doc_catalog(repo_id, language_code, generated_at);

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
CREATE INDEX IF NOT EXISTS idx_doc_page_repo ON doc_page(repo_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_doc_page_slug_language
ON doc_page(repo_id, language_code, slug);

CREATE VIRTUAL TABLE IF NOT EXISTS code_node_fts USING fts5(
  id UNINDEXED,
  repo_id UNINDEXED,
  type,
  name,
  file_path,
  language,
  symbol_id,
  summary,
  signature,
  docstring,
  tokenize = 'unicode61'
);

CREATE VIRTUAL TABLE IF NOT EXISTS code_chunk_fts USING fts5(
  id UNINDEXED,
  repo_id UNINDEXED,
  node_id UNINDEXED,
  file_path,
  start_line UNINDEXED,
  end_line UNINDEXED,
  content,
  tokenize = 'unicode61'
);
`;
