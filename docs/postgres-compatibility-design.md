# PostgreSQL Compatibility Design

## 1. Goal

CodeWiki currently ships as a local-first SQLite application. PostgreSQL support should
make the same backend, CLI, MCP server, and frontend workflows usable with a shared
PostgreSQL database while keeping SQLite as the default embedded mode.

The compatibility target is not a one-to-one port of every SQLite extension. The first
production-ready milestone should make repository registration, analysis, graph storage,
wiki storage, LLM run storage, and basic retrieval work on PostgreSQL. Full-text search
and vector search can then be upgraded from compatibility fallbacks to PostgreSQL-native
implementations.

## 2. Current State

The persistence entrypoint is SQLite-specific:

- `backend/app/config.py` defaults `database_url` to
  `sqlite+aiosqlite:///./data/codewiki.sqlite3`.
- `backend/app/db/store.py` exposes `SQLiteStore`.
- `backend/app/db/base.py` owns `BaseSQLiteStore`, creates a SQLite engine, opens direct
  `sqlite3` connections, runs SQLite PRAGMAs, loads `sqlite-vec`, creates FTS5 virtual
  tables, and performs lightweight SQLite-only migrations.
- `backend/app/db/utils.py` only parses SQLite database URLs.
- API, CLI, MCP, and service modules commonly type their store dependencies as
  `SQLiteStore`.

Most data models are SQLAlchemy ORM models and are close to portable. The main
PostgreSQL blockers are SQLite-specific schema setup, raw SQL, FTS5, sqlite-vec, and the
public store type name leaking through the application boundary.

Additional compatibility hazards that must be addressed explicitly:

- Several timestamp-like columns are mapped as `Text` while using
  `server_default=text("CURRENT_TIMESTAMP")`. PostgreSQL returns a native timestamp value
  for `CURRENT_TIMESTAMP`, so the schema needs either explicit text casts or native
  timestamp columns.
- `BaseSQLiteStore.connect()` returns `sqlite3.Connection` and is used by schema setup
  and tests. PostgreSQL needs a clearly defined equivalent or an intentional replacement.
- Lightweight migrations currently use `PRAGMA table_info(...)` plus `ALTER TABLE ADD
  COLUMN`. PostgreSQL requires SQLAlchemy inspector checks or `ALTER TABLE ... ADD
  COLUMN IF NOT EXISTS`.
- Vector inserts rely on `cursor.lastrowid`, which is SQLite-specific. PostgreSQL
  vector tables need `INSERT ... RETURNING id`.
- Batch sizing is hard-coded as `SQLITE_SAFE_BATCH_SIZE = 500` in multiple repository
  files, even though SQLite and PostgreSQL have different parameter and transaction
  limits.
- Several text JSON columns use `server_default="{}"` or `server_default="[]"`. In
  PostgreSQL these strings can be interpreted incorrectly during DDL unless emitted as
  quoted text defaults.
- `get_store()` is cached with `lru_cache`; a PostgreSQL engine brings connection-pool
  lifecycle concerns that SQLite file handles mostly hide.

## 3. Compatibility Targets

### In Scope

- Accept PostgreSQL URLs such as
  `postgresql+psycopg://user:password@host:5432/codewiki`.
- Require PostgreSQL 15 or newer for supported deployments. This keeps room for
  `ADD COLUMN IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`, `websearch_to_tsquery`, and
  current pgvector packages without carrying older server compatibility branches.
- Keep SQLite as the default and preserve existing SQLite behavior.
- Use the same repository/service/API/CLI/MCP workflows against either backend where
  possible.
- Support core relational persistence on PostgreSQL:
  - repositories
  - analysis runs
  - code nodes and edges
  - graph communities and community edges
  - code chunks
  - wiki catalogs and pages
  - LLM run records and cache lookup
- Provide PostgreSQL-compatible fallbacks for graph node and code chunk text search.
- Make vector search backend-specific:
  - SQLite uses `sqlite-vec`.
  - PostgreSQL can initially disable vector search or use text fallback.
  - A later milestone adds `pgvector`.

### Out of Scope for the First Milestone

- Automatic migration from existing SQLite files to PostgreSQL.
- Transparent cross-database replication.
- Multi-user authorization or tenancy.
- Replacing every SQLite-specific optimization with an equivalent PostgreSQL optimization
  in the first pass.

## 4. Design Principles

- Keep transport layers thin. FastAPI routes, CLI commands, and MCP handlers should keep
  calling store methods, not branching on database type.
- Keep domain services database-agnostic. Analysis, GraphRAG, wiki, and incremental
  services should not inspect SQL dialect names.
- Encapsulate SQL dialect differences in the persistence layer.
- Preserve local-first SQLite ergonomics.
- Prefer SQLAlchemy Core/ORM dialect helpers over handwritten dialect-specific strings
  when practical.
- Explicitly document feature degradation. If PostgreSQL vector search is unavailable,
  retrieval should degrade predictably instead of failing at startup.
- Keep schema object names globally unique within a PostgreSQL schema. PostgreSQL index
  names are schema-scoped, so new tsvector/GIN indexes must use globally unique names
  such as `idx_code_node_search_vector`, not names that could collide with indexes on
  other tables.

## 5. Proposed Architecture

### 5.1 Store Factory

Replace the single SQLite factory with a database URL dispatcher.

```text
Settings.database_url
  -> create_store(database_url)
       sqlite / sqlite+aiosqlite      -> SQLiteStore
       postgresql / postgresql+psycopg -> PostgresStore
```

Suggested module layout:

```text
backend/app/db/
  base.py                 # database-neutral BaseStore
  sqlite.py               # SQLiteStoreBase / SQLite dialect setup
  postgres.py             # PostgresStoreBase / PostgreSQL dialect setup
  store.py                # CodeWikiStore facade + create_store/get_store
  dialects.py             # small helper objects for backend-specific SQL
  schema.py               # SQLite auxiliary schema only, or split by backend
```

The facade class should be renamed to a neutral type and composed through a shared mixin
facade:

```python
class StoreRepositoryMixin(
    RepoRepositoryMixin,
    AnalysisRunRepositoryMixin,
    CodeGraphRepositoryMixin,
    GraphRAGRepositoryMixin,
    WikiRepositoryMixin,
    LLMRunRepositoryMixin,
):
    """Common repository API shared by all database backends."""


class SQLiteStore(StoreRepositoryMixin, SQLiteStoreBase):
    """SQLite-backed persistence facade."""


class PostgresStore(StoreRepositoryMixin, PostgresStoreBase):
    """PostgreSQL-backed persistence facade."""


CodeWikiStore = SQLiteStore | PostgresStore
```

For backward compatibility, `SQLiteStore` can remain as an alias or subclass while
internal annotations move to `CodeWikiStore`. Do not introduce a wide `StoreProtocol`
unless the project is ready to list and maintain every repository method signature; the
current concrete union is simpler and less brittle.

Repository mixins can continue to depend on `self.orm_session()`, `self.engine`, and
`self.dialect`. They should not call SQLite-only helpers such as `self.connect()` unless
the method is guarded by backend capability checks.

### 5.2 Base Store Responsibilities

`BaseStore` should own database-neutral behavior:

- SQLAlchemy `engine`
- `session_factory`
- `orm_session()`
- `ensure_schema()` using `Base.metadata.create_all()`
- common transaction helpers
- dialect helper access

SQLite-specific behavior moves out of `BaseStore`:

- `sqlite3.connect`
- PRAGMAs
- `sqlite_vec.load`
- `AUXILIARY_SCHEMA_SQL`
- `PRAGMA table_info`
- `sqlite_master`

PostgreSQL-specific behavior goes into `PostgresStoreBase`:

- engine URL passthrough
- explicit pool configuration
- extension setup for later `pgvector`
- PostgreSQL schema patch checks using SQLAlchemy inspector
- optional connect event hooks for settings such as `search_path`

Recommended PostgreSQL engine defaults:

```python
create_engine(
    database_url,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
    pool_recycle=1800,
    future=True,
)
```

These values match modest local/server deployments and should be configurable later for
multi-user installations. SQLite should keep its current low-overhead file-backed setup.

SQLAlchemy connect events should remain backend-specific:

- SQLite connect event:
  - PRAGMA configuration
  - `sqlite-vec` extension loading
- PostgreSQL connect event:
  - optional `SET search_path`
  - optional per-connection settings such as statement timeouts
  - no SQLite extension loading

Transaction isolation should also be explicit. SQLite WAL effectively gives the current
single-user workflow serial behavior around writes, while PostgreSQL defaults to
`READ COMMITTED`. The first PostgreSQL milestone should accept `READ COMMITTED` because
CodeWiki still writes through short `orm_session()` transactions. If concurrent analyze
jobs become supported, repo-level advisory locks or stricter transaction boundaries must
be added around destructive replace operations.

`get_store()` remains cached for now, but the lifecycle needs one more method:

```python
def close(self) -> None:
    self.engine.dispose()
```

Whenever CLI config changes `CODEWIKI_DATABASE_URL`, it must call `get_store.cache_clear()`
and dispose the previous engine if one exists. Long-lived API processes should treat a
database URL change as requiring process restart; hot-swapping pools in a running server
is out of scope.

### 5.3 Connection API

The current `connect()` method is SQLite-specific and returns `sqlite3.Connection`.
Production code uses it during `ensure_schema()`, and tests use it for direct SQLite
inspection. PostgreSQL support should not pretend that the same DB-API connection has
the same behavior.

Recommended split:

```python
class BaseStore:
    def raw_connection(self):
        return self.engine.raw_connection()

    def sql_connection(self):
        return self.engine.begin()


class SQLiteStoreBase(BaseStore):
    def connect(self) -> sqlite3.Connection:
        """Backward-compatible SQLite-only direct connection for existing tests."""


class PostgresStoreBase(BaseStore):
    def connect(self):
        raise NotImplementedError(
            "Direct sqlite3-style connect() is not supported for PostgreSQL; "
            "use orm_session(), sql_connection(), or SQLAlchemy inspector helpers."
        )
```

New production code should use `orm_session()`, `sql_connection()`, or SQLAlchemy
inspection. Existing SQLite tests can keep `store.connect()` while PostgreSQL tests use
backend-neutral helpers. This avoids creating a fake PG `connect()` API that would leak
psycopg-specific behavior into the app.

### 5.4 URL Parsing

Replace `sqlite_path_from_url()` as the only URL entrypoint with:

```python
def database_backend_from_url(database_url: str) -> Literal["sqlite", "postgresql"]:
    ...
```

SQLite still needs path extraction. PostgreSQL should keep the URL untouched.

Accepted schemes:

- SQLite:
  - `sqlite:///path`
  - `sqlite+aiosqlite:///path`
- PostgreSQL:
  - `postgresql://...`
  - `postgresql+psycopg://...`

The recommended PostgreSQL driver should be `psycopg`, not `psycopg2`.

The current default URL includes `sqlite+aiosqlite`, but the application creates a
synchronous SQLAlchemy engine. For compatibility, URL handling should normalize
`sqlite+aiosqlite:///...` to the synchronous SQLite engine URL internally. PostgreSQL
should likewise use the synchronous driver form `postgresql+psycopg://...`; async
drivers are out of scope until the store layer is made async end-to-end.

## 6. SQL Dialect Differences

### 6.1 Insert Ignore and Upsert

Current SQLite code uses raw SQL such as:

- `INSERT OR IGNORE INTO code_edge ...`
- `INSERT OR IGNORE INTO code_chunk ...`
- `INSERT OR IGNORE INTO graph_community ...`
- `ON CONFLICT(id) DO UPDATE ...`

PostgreSQL supports `ON CONFLICT DO NOTHING` and `ON CONFLICT (...) DO UPDATE`, but not
`INSERT OR IGNORE`.

Recommended approach:

- For ORM tables, use SQLAlchemy dialect insert helpers:
  - `sqlalchemy.dialects.sqlite.insert`
  - `sqlalchemy.dialects.postgresql.insert`
- Provide helper methods:

```python
store.dialect.insert_ignore(table, values, conflict_columns)
store.dialect.upsert(table, values, conflict_columns, update_columns)
```

For FTS or virtual tables, keep backend-specific repository branches.

### 6.2 Table Existence and Schema Inspection

Current code uses:

- `sqlite_master`
- `PRAGMA table_info(...)`

Replace with SQLAlchemy inspection where possible:

```python
from sqlalchemy import inspect

inspector = inspect(engine)
inspector.has_table("code_node")
inspector.get_columns("repo")
```

This works for both SQLite and PostgreSQL and removes custom SQL from most schema
checks.

### 6.3 Lightweight Schema Migrations

`BaseSQLiteStore._ensure_columns()` currently performs historical lightweight migrations
for columns such as:

- `repo.git_url`
- `repo.commit_hash`
- `llm_run.response_content`
- `llm_run.response_usage_json`
- `doc_catalog.language_code`
- `doc_page.language_code`
- `graph_community.parent_id`
- `graph_community.rank`

This must become a backend-neutral schema patch layer:

```python
@dataclass(frozen=True)
class ColumnPatch:
    table: str
    column: str
    ddl_by_backend: dict[str, str]
```

SQLite implementation:

```sql
ALTER TABLE repo ADD COLUMN git_url TEXT
```

PostgreSQL implementation:

```sql
ALTER TABLE repo ADD COLUMN IF NOT EXISTS git_url TEXT
```

The existence check should use SQLAlchemy inspector for both backends before executing
DDL. PostgreSQL DDL should still use `IF NOT EXISTS` as a second guard because schema
inspection and DDL are not atomic under concurrent startup.

Long term, Alembic is the cleaner migration story. The first PostgreSQL milestone can
keep the lightweight patch system, but it must be explicit and tested on both backends.

### 6.4 JSON Storage

Current `JSONText` serializes dict/list fields into `Text`.

This is portable and can remain for the first PostgreSQL milestone. It avoids immediate
JSONB migration complexity. A later migration can introduce a `PortableJSON` type:

- SQLite: `Text` with JSON serialization
- PostgreSQL: `JSONB`

Do not start with JSONB unless query performance on JSON fields becomes a real
bottleneck.

### 6.5 Timestamp Columns

The current schema stores timestamp-like values as text while several columns use
`server_default=text("CURRENT_TIMESTAMP")`. PostgreSQL's `CURRENT_TIMESTAMP` is a native
timestamp value, not text.

Affected model fields include:

- `RepoRecord.created_at`
- `RepoRecord.updated_at`
- `GraphCommunityRecord.created_at`
- `GraphCommunityEdgeRecord.created_at`
- `CodeChunkEmbeddingRecord.created_at`
- `DocCatalogRecord.generated_at`
- `DocPageRecord.updated_at`
- `LLMRunRecord.created_at`

There are two viable strategies:

1. Keep text timestamps for compatibility and use backend-specific defaults.
   - SQLite: `CURRENT_TIMESTAMP`
   - PostgreSQL: `CURRENT_TIMESTAMP::text`
2. Migrate to `DateTime(timezone=True)` and normalize record serializers/API payloads.

The first PostgreSQL milestone should use strategy 1 because the application already
passes ISO strings from `now_iso()` and many API payloads treat timestamps as strings.
Introduce a helper:

```python
def timestamp_text_default(dialect_name: str) -> str:
    if dialect_name == "postgresql":
        return "CURRENT_TIMESTAMP::text"
    return "CURRENT_TIMESTAMP"
```

The model definitions cannot easily vary `server_default` by runtime dialect. Therefore
the practical first step is:

- Keep ORM columns as `Text`.
- Remove or avoid relying on server defaults in PostgreSQL-sensitive paths.
- Ensure application writes explicit `now_iso()` values for records created by CodeWiki.
- In PostgreSQL schema patching, adjust existing text timestamp defaults to
  `CURRENT_TIMESTAMP::text` where defaults are needed.

A later migration can convert timestamps to native `DateTime(timezone=True)` once API
compatibility expectations are updated.

### 6.6 Booleans and Defaults

The current models use SQLAlchemy booleans and text server defaults such as `"0"` or
`"{}"`. SQLAlchemy handles many differences, but PostgreSQL is stricter about default
types.

Audit these fields during PostgreSQL schema creation:

- `CodeEdgeRecord.is_inferred`
- `LLMRunRecord.cached`
- JSON text default columns
- timestamp text defaults using `CURRENT_TIMESTAMP::text`

Boolean server defaults should use SQLAlchemy `false()` or backend-specific DDL rather
than string `"0"` if PostgreSQL schema creation rejects the current defaults.

Affected boolean defaults:

- `CodeEdgeRecord.is_inferred` currently uses `server_default="0"`.
- `LLMRunRecord.cached` currently uses `server_default="0"`.

PostgreSQL-safe forms:

```python
from sqlalchemy import false

server_default=false()
```

or backend-specific DDL:

```sql
DEFAULT false
```

JSON text defaults need the same level of care. Current affected fields include:

- `CodeNodeRecord.metadata_json` default `{}`.
- `CodeEdgeRecord.metadata_json` default `{}`.
- `AnalysisRunRecord.stats_json` default `{}`.
- `LLMRunRecord.response_usage_json` default `{}`.
- `GraphCommunityRecord.node_ids_json` default `[]`.
- `GraphCommunityEdgeRecord.evidence_edge_ids_json` default `[]`.
- `DocCatalogRecord.structure_json` default `{"items":[]}`.
- `DocPageRecord.source_refs_json` default `[]`.
- `DocPageRecord.graph_refs_json` default `[]`.

Because these columns are currently `Text`, PostgreSQL DDL must emit quoted text
defaults, not array or JSON literals. Safe examples:

```python
server_default=text("'{}'")
server_default=text("'[]'")
server_default=text("'{\"items\":[]}'")
```

or schema patch DDL:

```sql
ALTER TABLE analysis_run
  ALTER COLUMN stats_json SET DEFAULT '{}';
```

Do not rely on bare `server_default="{}"` or `server_default="[]"` for PostgreSQL schema
creation. If a future `PortableJSON` switches PostgreSQL to `JSONB`, defaults must then
change to JSONB-safe forms such as `'{}'::jsonb` and `'[]'::jsonb`.

### 6.7 Batch Size Policy

The code currently repeats `SQLITE_SAFE_BATCH_SIZE = 500` and local `_chunks()` helpers
across graph, chunk, community, and embedding repositories. PostgreSQL has a much higher
parameter limit than SQLite, and optimal transaction sizes may differ.

Move batching to one helper module:

```python
def write_batch_size(dialect_name: str) -> int:
    if dialect_name == "sqlite":
        return 500
    if dialect_name == "postgresql":
        return 2000
    return 500
```

The exact PostgreSQL value should be benchmarked. The important design point is that
batch size becomes backend-configurable instead of being encoded as a SQLite constant in
multiple repositories.

## 7. Full-Text Search Strategy

### 7.1 Current SQLite FTS5

SQLite uses two FTS5 virtual tables:

- `code_node_fts`
- `code_chunk_fts`

Queries use:

- `MATCH`
- `bm25(...)`
- custom FTS token query construction
- FTS backfill through `_sync_code_node_fts_if_needed()`

This will not run on PostgreSQL.

### 7.2 Milestone 1 PostgreSQL Fallback

For the first milestone, PostgreSQL should use portable `ILIKE` fallback search:

- graph node search:
  - search `name`, `symbol_id`, `file_path`, `summary`
  - keep existing rank heuristic from `_search_code_nodes_like`
- code chunk search:
  - search `content` and `file_path`
  - return deterministic scores based on match location and order

The repository API remains the same:

```python
search_code_nodes(...)
search_code_chunks_fts(...)
```

The implementation branches internally:

```python
if self.dialect.supports_fts5:
    ...
else:
    ...
```

All direct writes or deletes against FTS shadow tables must be guarded the same way. For
example, `RepoRepositoryMixin.delete_repo()` currently runs:

```sql
DELETE FROM code_chunk_fts WHERE repo_id = :repo_id
```

That statement must be SQLite-only:

```python
if self.dialect.supports_fts5:
    session.execute(text("DELETE FROM code_chunk_fts WHERE repo_id = :repo_id"), ...)
```

PostgreSQL milestone 1 has no `code_chunk_fts` table, so unguarded cleanup SQL would
break repository deletion.

Naming can be cleaned up later; initially keep `search_code_chunks_fts` to avoid broad
service changes.

`_sync_code_node_fts_if_needed()` becomes a SQLite-only maintenance hook. PostgreSQL
milestone 1 has no FTS shadow table, so the equivalent hook is a no-op. In milestone 2,
the hook should be replaced with a backend-specific search-index sync method:

```python
store.search_index.sync_code_nodes_if_needed()
```

SQLite implementation rebuilds missing FTS5 rows. PostgreSQL tsvector implementation
updates materialized search rows or generated columns only when needed.

### 7.3 Milestone 2 PostgreSQL Native Search

Add PostgreSQL `tsvector` search:

- For `code_node`, build a weighted `tsvector` from name, path, language, symbol id,
  summary, signature, and docstring.
- For `code_chunk`, build a `tsvector` from file path and content.
- Add GIN indexes.
- Use `websearch_to_tsquery` or `plainto_tsquery`.
- Use `ts_rank_cd` for ranking.

Implementation choices:

1. Generated columns if PostgreSQL version support is guaranteed.
2. Materialized columns updated by application code.
3. Trigger-maintained `tsvector` columns.

Application-maintained materialized columns are easiest to control in a project that
already performs explicit batch writes.

### 7.4 Query Construction

`_node_fts_query()` currently emits SQLite FTS5 prefix syntax such as `"term"*`. This
cannot be reused for PostgreSQL. Query construction should be split by backend:

```python
class SearchDialect:
    def node_query(self, query: str) -> object: ...
    def chunk_query(self, query: str) -> object: ...
```

SQLite:

```text
"symbol"* OR "path"*
```

PostgreSQL fallback:

```text
ILIKE '%symbol%'
```

PostgreSQL native search:

```sql
websearch_to_tsquery('simple', :query)
```

This split prevents leaking SQLite FTS5 syntax into PostgreSQL search paths.

## 8. Vector Search Strategy

### 8.1 Current SQLite Vec

SQLite vector support is tightly bound to `sqlite-vec`:

- dynamic virtual tables named `code_chunk_embedding_vec_<dimensions>`
- `rowid`
- `embedding MATCH :embedding`
- `sqlite_vec.serialize_float32`
- `cursor.lastrowid` after vector insert

This has no PostgreSQL equivalent.

### 8.2 Milestone 1 PostgreSQL Behavior

PostgreSQL should support embedding metadata persistence but gracefully skip vector
nearest-neighbor search unless vector support is configured.

Recommended behavior:

- `replace_code_chunk_embeddings` and `sync_code_chunk_embeddings` can either:
  - store metadata only and leave raw vectors out, or
  - be disabled with a clear `VectorSearchUnavailable` result.
- `search_code_chunk_embeddings` returns `[]` when vector backend is unavailable.
- GraphRAG retriever falls back to FTS/ILIKE and graph expansion.

This keeps PostgreSQL usable for graph/wiki workflows without making `pgvector` mandatory
on day one.

### 8.3 Milestone 2 pgvector

Add optional `pgvector` support:

- Dependency: `pgvector` Python package.
- Database extension:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

- Schema options:
  - Single table with one `vector` column if dimensions are fixed by configured embedding
    model.
  - Separate tables per dimension, similar to current SQLite dynamic table approach.
  - Store vector as array/bytea plus separate search table.

Recommended path:

- Add one vector table per dimension:

```text
code_chunk_embedding_vec_<dimensions>
  id
  repo_id
  model
  chunk_id
  embedding vector(<dimensions>)
```

- Use cosine distance:

```sql
ORDER BY embedding <=> :query_embedding
LIMIT :limit
```

The existing `vec_table` and `vec_rowid` metadata shape can be generalized to
`vector_table` and `vector_id` later, but the first implementation can keep column names
for compatibility.

PostgreSQL inserts must not rely on `cursor.lastrowid`. Vector insert SQL should return
the inserted identifier explicitly:

```sql
INSERT INTO code_chunk_embedding_vec_1536 (embedding, repo_id, model, chunk_id)
VALUES (:embedding, :repo_id, :model, :chunk_id)
RETURNING id
```

SQLite vector inserts can keep using `lastrowid` behind the SQLite vector backend. The
generic embedding repository should only receive the returned vector identifier from the
backend adapter.

Vector serialization and loading must also move behind the backend adapter. SQLite stores
vectors as serialized float32 blobs and uses:

```python
sqlite_vec.serialize_float32(vector)
struct.iter_unpack("f", blob)
```

pgvector returns vector values as Python sequences through its SQLAlchemy/psycopg
adapter, so it should not pass through `_deserialize_float32()`. The generic repository
should call:

```python
store.vector_backend.load_vector(session, row.vec_table, row.vec_rowid)
```

Backend behavior:

- SQLite: load blob by `rowid`, deserialize float32 bytes.
- PostgreSQL pgvector: load by `id` or return already-loaded vector values.
- PostgreSQL no-op vector backend: return `[]`.

The existing `_embedding_row_matches()` integrity check also becomes backend-specific.
SQLite currently checks:

```sql
SELECT 1 FROM {vec_table} WHERE rowid = :vec_rowid
```

PostgreSQL pgvector should check:

```sql
SELECT 1 FROM {vec_table} WHERE id = :vector_id
```

or avoid the extra existence query if embedding metadata and vector value are stored in
the same table with a foreign-key relationship.

Finally, `list_code_chunk_embeddings()` currently performs one `_load_vector()` call per
metadata row. That N+1 pattern is acceptable for small SQLite lists but should be avoided
in PostgreSQL pgvector. The vector backend should expose bulk loading:

```python
store.vector_backend.load_vectors(session, rows)
```

SQLite can implement it as batched rowid lookups. PostgreSQL can join metadata and vector
tables in one query or return vectors directly from a unified table.

### 8.4 Vector Cleanup

`RepoRepositoryMixin.delete_repo()` currently discovers SQLite vector tables with:

```sql
SELECT name FROM sqlite_master WHERE name LIKE 'code_chunk_embedding_vec_%'
```

This cleanup should move into the vector backend:

```python
store.vector_backend.delete_repo_vectors(session, repo_id)
```

PostgreSQL discovery can use SQLAlchemy inspector or `information_schema.tables`:

```sql
SELECT table_name
FROM information_schema.tables
WHERE table_schema = current_schema()
  AND table_name LIKE 'code_chunk_embedding_vec_%'
```

If pgvector uses a single fixed table instead of dimension-specific tables, the cleanup
implementation simply deletes rows from that table.

## 9. Repository-by-Repository Impact

### `base.py`

Split SQLite-specific code out of `BaseSQLiteStore`.

Required changes:

- Introduce database-neutral `BaseStore`.
- Move direct sqlite connections to `SQLiteStoreBase`.
- Define `connect()` as SQLite-only compatibility API and introduce backend-neutral
  `sql_connection()` / inspector helpers for new code.
- Use SQLAlchemy inspector for schema checks.
- Move FTS5 setup to SQLite-only setup.
- Add PostgreSQL setup path.
- Move lightweight column migration logic to backend-aware schema patch helpers.
- Keep the historical `doc_page` index migration explicit:
  - `DROP INDEX IF EXISTS idx_doc_page_slug`
  - `CREATE UNIQUE INDEX IF NOT EXISTS idx_doc_page_slug_language ...`
  This SQL is PostgreSQL-compatible and is harmless on new PostgreSQL databases where
  `Base.metadata.create_all()` already created the model-declared unique index, but the
  migration should remain documented as a legacy SQLite upgrade step.

### `store.py`

Required changes:

- Rename facade to `CodeWikiStore`.
- Keep `SQLiteStore` for compatibility.
- Add `PostgresStore`.
- Add `create_store(database_url)`.
- Update `get_store()` to dispatch by URL scheme.
- Use a shared `StoreRepositoryMixin` so `SQLiteStore` and `PostgresStore` do not repeat
  the long repository mixin list.

### `database.py`, API, CLI, MCP, Services

Required changes:

- Replace public annotations from `SQLiteStore` to `CodeWikiStore`.
- Keep `SQLiteStore` exported for tests and existing imports during migration.
- Avoid `isinstance(store, SQLiteStore)` checks. Replace with capability/protocol checks.
- Expect a broad annotation cleanup across roughly these areas:
  - `backend/app/services/*`
  - `backend/app/services/wiki/*`
  - `backend/app/services/graphrag/*`
  - `backend/app/api/*`
  - `backend/app/cli/*`
  - `backend/app/mcp_server/*`
  - SQLite-specific tests under `tests/backend/*`

### `code_graph.py`

Required changes:

- Replace `INSERT OR IGNORE` with dialect insert ignore.
- Branch node FTS writes/search:
  - SQLite FTS5
  - PostgreSQL ILIKE fallback, later tsvector
- Keep `ON CONFLICT(id) DO UPDATE`, preferably via SQLAlchemy dialect insert helper.
- Move `_node_fts_query()` behind a search dialect adapter.
- Treat `_sync_code_node_fts_if_needed()` as SQLite-only until PostgreSQL tsvector sync
  exists.

### `code_chunks.py`

Required changes:

- Replace chunk insert ignore with dialect helper.
- Branch FTS writes/search:
  - SQLite `code_chunk_fts`
  - PostgreSQL fallback or tsvector.
- Move duplicated `_chunks()` and `SQLITE_SAFE_BATCH_SIZE` to a shared batch helper.

### `communities.py`

Required changes:

- Replace `INSERT OR IGNORE` for communities and community edges.
- JSON text mappings are portable enough for first milestone.
- Move duplicated `_chunks()` and batch sizing to shared helpers.

### `embeddings.py`

Required changes:

- Split vector backend:
  - SQLiteVecEmbeddingBackend
  - NoopEmbeddingBackend for PostgreSQL milestone 1
  - PgVectorEmbeddingBackend for milestone 2
- Remove direct `sqlite_master`, virtual table creation, `rowid`, and `sqlite_vec` from
  generic repository logic.
- Replace `cursor.lastrowid` with backend-returned vector identifiers. PostgreSQL vector
  inserts must use `RETURNING`.
- Confirm `CodeChunkEmbeddingRecord.__allow_unmapped__` remains dialect-neutral. The
  unmapped `embedding` Python attribute is an ORM mapping concern, not a SQL dialect
  feature, so it should behave the same on SQLite and PostgreSQL.

### `repos.py`

Required changes:

- Replace `sqlite_master` dynamic vector table cleanup with vector backend cleanup.
- Keep repo CRUD generic.

### `mappers.py`

No database-specific changes are expected. The mapper functions accept
`Mapping[str, Any]` and convert ORM rows or raw SQL mapping rows into service-layer data
classes. They should remain backend-neutral, but PostgreSQL tests should still exercise
rows produced by PostgreSQL search fallback/native search because column names and JSON
text decoding must match SQLite results.

### `repositories/graphrag.py`

No direct database-specific changes are expected. This file is a compatibility mixin
that combines code chunk, embedding, and community repositories. It should continue to
compose the same repository mixins after vector and search behavior move behind backend
adapters.

### `schema.py`

Required changes:

- Move `AUXILIARY_SCHEMA_SQL` into SQLite-only schema setup or split schema constants by
  backend.
- Do not import or execute FTS5 SQL from the generic base store.
- Add PostgreSQL search-index DDL only when native tsvector search is implemented.

### `cli/config.py` and `env_config.py`

Required changes:

- Keep `CODEWIKI_DATABASE_URL` in the common config keys.
- Add validation/help text that accepts both SQLite and PostgreSQL URL examples.
- Avoid rejecting PostgreSQL URLs in CLI config flows.
- Update interactive `codewiki config` prompts to offer database URL configuration.
  Today the prompt flow focuses on LLM and wiki language settings; PostgreSQL users need
  a guided way to set `CODEWIKI_DATABASE_URL`.
- Implement URL validation in `create_store()` and reuse the same parser in CLI config
  validation so unsupported schemes fail with one clear message.

### `docker-compose.yml`

Required changes for PostgreSQL development support:

- Add a `postgres` service.
- Prefer an image with pgvector available for later phases, such as `pgvector/pgvector`.
- Add a persistent data volume.
- Add a healthcheck using `pg_isready`.
- Wire the app service with `depends_on` and
  `CODEWIKI_DATABASE_URL=postgresql+psycopg://...`.
- Keep SQLite compose usage possible for local-first users.

Example shape:

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: codewiki
      POSTGRES_USER: codewiki
      POSTGRES_PASSWORD: codewiki
    volumes:
      - postgres-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U codewiki -d codewiki"]
      interval: 5s
      timeout: 5s
      retries: 20

  app:
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      CODEWIKI_DATABASE_URL: postgresql+psycopg://codewiki:codewiki@postgres:5432/codewiki

volumes:
  postgres-data:
```

## 10. Configuration

Add documentation and examples for PostgreSQL:

```env
CODEWIKI_DATABASE_URL=postgresql+psycopg://codewiki:codewiki@localhost:5432/codewiki
```

Optional vector configuration for later:

```env
CODEWIKI_VECTOR_BACKEND=pgvector
```

For SQLite, keep defaults unchanged:

```env
CODEWIKI_DATABASE_URL=sqlite+aiosqlite:///./data/codewiki.sqlite3
```

## 11. Dependencies

Add PostgreSQL dependencies:

```toml
dependencies = [
  "psycopg[binary]>=3.2.0",
]
```

For later pgvector support:

```toml
dependencies = [
  "pgvector>=0.3.0",
]
```

`sqlite-vec` should remain installed for SQLite unless vector support becomes optional by
extra.

Long term, database-specific extras would be cleaner:

```toml
[project.optional-dependencies]
sqlite = ["sqlite-vec>=0.1.9"]
postgres = ["psycopg[binary]>=3.2.0"]
pgvector = ["pgvector>=0.3.0"]
```

The current package can keep `sqlite-vec` as a core dependency for compatibility, but
PostgreSQL code paths must import it conditionally inside the SQLite vector backend only.
A PostgreSQL deployment that never uses SQLite should not fail because `sqlite-vec`
cannot load.

## 12. Migration Plan

### Phase 1: Store Abstraction

- Add neutral `CodeWikiStore` facade.
- Add `StoreRepositoryMixin`.
- Add `create_store()` URL dispatcher.
- Add `PostgresStore` as a stub that raises a clear unsupported-backend error after URL
  detection. This gives the factory a real branch without claiming PostgreSQL works yet.
- Keep `SQLiteStore` tests passing.
- Replace service/API/CLI/MCP annotations with neutral store type.
- Normalize sync URL handling for `sqlite+aiosqlite` and `postgresql+psycopg`.

Acceptance criteria:

- Existing SQLite test suite passes.
- `CODEWIKI_DATABASE_URL` still defaults to SQLite.
- No behavior change for current users.
- PostgreSQL URLs fail with a clear "not implemented yet" error instead of "only sqlite
  URLs are supported".
- CLI config can validate and persist both SQLite and PostgreSQL database URLs.

### Phase 2: PostgreSQL Relational Store

- Add `PostgresStore`.
- Add `psycopg` dependency.
- Make `Base.metadata.create_all()` work on PostgreSQL.
- Replace `sqlite_master` and `PRAGMA` checks with inspector-based helpers.
- Add backend-aware lightweight column migrations.
- Resolve text timestamp defaults by writing explicit `now_iso()` values and using
  PostgreSQL-safe defaults where required.
- Resolve text JSON defaults and boolean defaults so PostgreSQL schema creation succeeds.
- Convert insert ignore/upsert paths to dialect helpers.
- Centralize batch sizing.
- Disable or fallback FTS/vector behavior on PostgreSQL.

Acceptance criteria:

- Basic repo CRUD works on PostgreSQL.
- Cold analyze can persist nodes, edges, communities, chunks, wiki records, and LLM runs.
- Graph search works through ILIKE fallback.
- Vector search degrades cleanly.
- PostgreSQL schema creation succeeds from an empty database without manual DDL.

### Phase 3: PostgreSQL Search Quality

- Add PostgreSQL `tsvector` columns/tables and GIN indexes.
- Implement PostgreSQL graph node and chunk text search.
- Keep SQLite FTS5 unchanged.

Acceptance criteria:

- PostgreSQL text search returns comparable results to SQLite FTS for common queries.
- Search tests cover both fallback and native tsvector behavior.

### Phase 4: PostgreSQL Vector Search

- Add optional `pgvector` backend.
- Add extension setup.
- Add vector insert/list/search implementation.
- Add tests behind `CODEWIKI_TEST_POSTGRES_URL`.

Acceptance criteria:

- Embeddings can be inserted and searched on PostgreSQL with pgvector enabled.
- GraphRAG hybrid retrieval uses PostgreSQL vector hits when configured.

## 13. Testing Strategy

### Unit Tests

- Keep current SQLite tests.
- Add store factory tests for SQLite URLs, normalized SQLite driver URLs, PostgreSQL URLs,
  and unknown schemes.
- Add dialect helper tests for:
  - URL dispatch
  - insert ignore
  - upsert
  - table existence
  - FTS capability detection
  - vector capability detection

### Integration Tests

Use an environment-gated PostgreSQL test URL:

```bash
CODEWIKI_TEST_POSTGRES_URL=postgresql+psycopg://codewiki:codewiki@localhost:5432/codewiki_test pytest -q tests/backend
```

Tests should create isolated schemas or databases per run. The simplest local setup is a
Docker Compose service and a pytest fixture that truncates all tables between tests.

Existing tests should not directly construct `SQLiteStore(tmp_path / "codewiki.sqlite3")`
when they are intended to be backend-neutral. Introduce fixtures:

```python
@pytest.fixture
def sqlite_store(tmp_path): ...

@pytest.fixture
def postgres_store(): ...

@pytest.fixture(params=["sqlite", "postgresql"])
def store(request): ...
```

Tests that inspect SQLite internals with `PRAGMA table_info`, `sqlite_master`, or
`store.connect()` remain SQLite-only tests. Backend-neutral schema tests should use
SQLAlchemy inspector helpers.

PostgreSQL isolation options:

1. Create a temporary schema per test and set `search_path`.
2. Create a temporary database per test session and truncate tables between tests.
3. Run PostgreSQL tests serially at first; add parallel isolation later.

Schema-per-test is the best long-term fit because it avoids database creation privileges
and is compatible with CI service containers.

### CI

Initial CI can keep SQLite only. Add PostgreSQL CI once the relational milestone is
stable:

- PostgreSQL service container.
- Optional pgvector service image for future vector tests.
- `psycopg` installed.
- Run a focused PostgreSQL suite first.
- Expand to full backend suite as FTS/vector parity improves.

## 14. Rollout and Compatibility

Default behavior remains SQLite. PostgreSQL is opt-in through `CODEWIKI_DATABASE_URL`.

Recommended rollout:

1. Merge store abstraction with no user-visible behavior change.
2. Add PostgreSQL relational support and document feature limits.
3. Add PostgreSQL search improvements.
4. Add pgvector support.

Any unsupported PostgreSQL feature should fail softly at retrieval time with a clear
fallback, not fail during application startup.

Failure and degradation behavior should be centralized in dialect/backend adapters:

```python
class SearchBackend:
    def search_nodes(...): ...
    def search_chunks(...): ...


class VectorBackend:
    def search(...): ...
```

Expected decisions:

- FTS5 unavailable on PostgreSQL milestone 1: fall back to ILIKE search, not `[]`.
- Native PostgreSQL tsvector unavailable but PostgreSQL is otherwise usable: fall back to
  ILIKE search.
- Vector backend unavailable: return `[]` for vector hits and let GraphRAG continue with
  text search and graph expansion.
- pgvector explicitly requested but extension/setup fails: raise a clear startup/config
  error because the user requested that capability.
- PostgreSQL connection failure: fail application startup or CLI command execution with a
  clear database connection error; do not silently fall back to SQLite because that could
  write data to the wrong database.
- Unsupported URL scheme: fail in `create_store()` with the accepted scheme list.

## 15. Risks

- FTS parity: SQLite FTS5 and PostgreSQL text search rank differently.
- Vector parity: `sqlite-vec` and `pgvector` have different schema and query mechanics.
- Large writes: PostgreSQL may need different batch sizes and indexes for VS Code-scale
  graphs.
- Test isolation: PostgreSQL integration tests need stronger cleanup than SQLite temp
  files.
- Type leaks: many modules currently name `SQLiteStore`, so a careless migration can
  leave confusing public APIs.
- Text timestamps: keeping timestamp fields as `Text` avoids a wide API change, but
  requires careful default handling on PostgreSQL.
- Direct connection API: existing SQLite tests use `store.connect()`, but PostgreSQL
  should not expose a misleading sqlite3-compatible direct connection.

## 16. Recommended First PR

The first implementation PR should be intentionally small:

1. Introduce `CodeWikiStore` as the neutral facade.
2. Introduce `StoreRepositoryMixin` and keep `SQLiteStore` behavior unchanged.
3. Add URL backend detection and sync URL normalization.
4. Add a stub `PostgresStore` branch that raises a clear unsupported-backend error.
5. Replace app-level annotations from `SQLiteStore` to `CodeWikiStore`.
6. Add tests proving old SQLite URLs and unsupported PostgreSQL URLs produce clear
   behavior.

After that lands, PostgreSQL relational support can be added without mixing broad type
renames, factory changes, and SQL dialect work in the same change.
