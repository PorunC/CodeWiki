SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS repo (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  path TEXT NOT NULL,
  source_type TEXT NOT NULL DEFAULT 'local',
  git_url TEXT,
  commit_hash TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
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
CREATE INDEX IF NOT EXISTS idx_analysis_run_repo
  ON analysis_run(repo_id, started_at);

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
CREATE UNIQUE INDEX IF NOT EXISTS idx_code_chunk_hash
  ON code_chunk(repo_id, content_hash, file_path, start_line, end_line);

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

CREATE TABLE IF NOT EXISTS code_chunk_embedding (
  id TEXT PRIMARY KEY,
  repo_id TEXT NOT NULL REFERENCES repo(id) ON DELETE CASCADE,
  chunk_id TEXT NOT NULL REFERENCES code_chunk(id) ON DELETE CASCADE,
  model TEXT NOT NULL,
  dimensions INTEGER NOT NULL,
  vec_table TEXT NOT NULL,
  vec_rowid INTEGER NOT NULL,
  content_hash TEXT NOT NULL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_code_chunk_embedding_repo
  ON code_chunk_embedding(repo_id, model);
CREATE UNIQUE INDEX IF NOT EXISTS idx_code_chunk_embedding_chunk_model
  ON code_chunk_embedding(repo_id, chunk_id, model);
CREATE UNIQUE INDEX IF NOT EXISTS idx_code_chunk_embedding_vec_row
  ON code_chunk_embedding(vec_table, vec_rowid);

CREATE TABLE IF NOT EXISTS graph_community (
  id TEXT PRIMARY KEY,
  repo_id TEXT NOT NULL REFERENCES repo(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  level INTEGER NOT NULL DEFAULT 0,
  node_ids_json TEXT NOT NULL DEFAULT '[]',
  summary TEXT,
  summary_hash TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_graph_community_repo ON graph_community(repo_id);
CREATE INDEX IF NOT EXISTS idx_graph_community_level ON graph_community(repo_id, level);

CREATE TABLE IF NOT EXISTS doc_catalog (
  id TEXT PRIMARY KEY,
  repo_id TEXT NOT NULL REFERENCES repo(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  structure_json TEXT NOT NULL DEFAULT '{"items":[]}',
  generated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_doc_catalog_repo ON doc_catalog(repo_id, generated_at);

CREATE TABLE IF NOT EXISTS doc_page (
  id TEXT PRIMARY KEY,
  repo_id TEXT NOT NULL REFERENCES repo(id) ON DELETE CASCADE,
  slug TEXT NOT NULL,
  title TEXT NOT NULL,
  parent_slug TEXT,
  markdown TEXT NOT NULL DEFAULT '',
  source_refs_json TEXT NOT NULL DEFAULT '[]',
  graph_refs_json TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'draft',
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_doc_page_repo ON doc_page(repo_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_doc_page_slug ON doc_page(repo_id, slug);

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
  cached INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'success',
  error TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_llm_run_task ON llm_run(repo_id, task_type, cache_key);
CREATE INDEX IF NOT EXISTS idx_llm_run_created ON llm_run(repo_id, created_at);
"""
