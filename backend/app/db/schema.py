AUXILIARY_SCHEMA_SQL = """
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
"""
