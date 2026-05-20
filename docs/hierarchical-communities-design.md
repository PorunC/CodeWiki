# Hierarchical Communities Refactor Design

## Background

CodeWiki originally detected graph communities as one flat partition and capped the result at
`MAX_COMMUNITIES = 32`. That shape was too coarse for large repositories: architecture areas,
implementation modules, and detailed workflow clusters competed for the same flat list, and broad
community summaries could consume GraphRAG and wiki prompt budget without adding precise evidence.

The current implementation replaces the flat partition with bounded hierarchical communities and
keeps source-level facts separate from derived community facts.

## Goals

- Replace the hard flat cap with a bounded hierarchy.
- Preserve source graph semantics: `code_node` and `code_edge` remain source-level facts.
- Keep file nodes in the graph, but do not create source chunks for file nodes.
- Keep GraphRAG payloads compact by selecting deepest matching communities first and adding only
  necessary ancestors.
- Improve wiki catalog generation with both flat community summaries and nested hierarchy hints.
- Provide derived community edges without mixing them into `code_edge`.

## Non-Goals

- Do not turn communities into `code_node` records.
- Do not mix inferred community relationships into `code_edge`.
- Do not force wiki pages to mirror community hierarchy exactly. Communities guide catalog planning;
  they do not dictate it.
- Do not preserve old flat database semantics. New analyses are expected to rebuild community data.

## Implemented Pipeline

```text
source scan
  -> code graph
  -> high-resolution leaf partition
  -> community graph parent partition
  -> optional detail partition for oversized leaves
  -> graph_community(level, parent_id, rank)
  -> graph_community_edge derived relationships
  -> GraphRAG deepest-leaf selection + ancestor context
  -> wiki catalog flat summaries + nested hierarchy
```

Hierarchy levels:

- `level=0`: architecture parent communities.
- `level=1`: implementation child communities.
- `level=2`: detail communities for oversized implementation areas.

The detector uses a community-graph strategy for the first two levels and applies detail splitting
only when a child is large enough to justify another layer.

## Data Model

### `graph_community`

```text
id TEXT PRIMARY KEY
repo_id TEXT NOT NULL
name TEXT NOT NULL
level INTEGER NOT NULL DEFAULT 0
parent_id TEXT NULL
rank INTEGER NOT NULL DEFAULT 0
node_ids_json TEXT NOT NULL DEFAULT '[]'
summary TEXT NULL
summary_hash TEXT NULL
created_at TEXT DEFAULT CURRENT_TIMESTAMP
```

`parent_id` links each child/detail community to its parent. `rank` preserves deterministic ordering
inside a level or parent even after LLM naming changes.

`node_ids` semantics:

- deepest leaf community: exact source graph nodes assigned to that community;
- parent community: union of descendant `node_ids`;
- omitted tiny child partitions remain covered by their parent, so every graph node remains covered
  by at least one retained community.

### `graph_community_edge`

Community edges are derived analysis artifacts stored separately from `code_edge`:

```text
id TEXT PRIMARY KEY
repo_id TEXT NOT NULL
source_community_id TEXT NOT NULL
target_community_id TEXT NOT NULL
type TEXT NOT NULL
weight REAL NOT NULL DEFAULT 1.0
confidence REAL NOT NULL DEFAULT 1.0
reason TEXT NULL
evidence_edge_ids_json TEXT NOT NULL DEFAULT '[]'
created_at TEXT DEFAULT CURRENT_TIMESTAMP
```

Implemented edge types:

- `contains`: parent contains child/detail community.
- `calls_into`: aggregated `calls` relationship.
- `imports_from`: aggregated `imports`/`exports` relationship.
- `routes_to`: aggregated routing relationship.
- `depends_on`: fallback aggregate dependency type.

Dependency edges are aggregated from deepest leaf communities so parent/child node overlap does not
double-count source facts.

## Detection Algorithm

The detector returns `DetectedCommunity` objects instead of raw partitions:

```python
@dataclass(frozen=True)
class DetectedCommunity:
    key: str
    node_ids: list[str]
    level: int
    parent_key: str | None
    rank: int
```

`key` and `parent_key` are deterministic temporary keys. `CommunityRecordBuilder` resolves them into
stable database IDs and `parent_id` values after all records are known.

Partition resolutions:

```text
LEAF_RESOLUTION = 2.0
PARENT_RESOLUTION = 0.5
DETAIL_RESOLUTION = 3.0
```

The shared `_partition(graph, resolution=...)` passes resolution through to Leiden and NetworkX
Louvain. Fallback algorithms that do not support resolution keep their existing behavior.

### Community Graph Phase

```text
1. Build the weighted source graph from filtered graph nodes and code edges.
2. Run high-resolution partitioning to produce implementation leaf communities.
3. Build a community graph where each leaf is a node.
4. Aggregate cross-leaf source graph edge weights into community graph edge weights.
5. Run low-resolution partitioning on the community graph to produce parents.
6. Emit level=0 parents and level=1 children.
```

Small leaf handling:

```python
target = max(
    community_graph.neighbors(small_leaf_index),
    key=lambda neighbor_index: community_graph[small_leaf_index][neighbor_index]["weight"],
    default=None,
)
```

A tiny leaf is merged into its strongest neighboring leaf when the edge is meaningful. If no strong
neighbor exists, the tiny leaf is not emitted as a child; its nodes stay covered by the parent.
Singleton small parents are similarly merged into the strongest neighboring parent when possible.

### Detail Phase

Oversized level-1 communities can be split into level-2 detail communities when they exceed detail
thresholds:

```text
DETAIL_SPLIT_NODE_THRESHOLD = 120
DETAIL_SPLIT_FILE_THRESHOLD = 32
MIN_DETAIL_NODES = 12
MAX_DETAIL_COMMUNITIES_PER_CHILD = 8
```

Detail communities are bounded and only emitted when the partition has useful signal. If detail
splitting is not useful, the level-1 child remains the deepest leaf.

## Record Building

Stable community IDs follow this shape:

```text
{repo_id}:community:{level}:{digest}
```

The digest includes level, parent key/id context, and sorted node IDs so IDs stay stable when sibling
rank or LLM-generated names change.

`CommunityRecordBuilder` resolves nested parent links for any supported depth:

```text
1. Build records in level order.
2. Store temporary key -> official community ID as records are created.
3. Resolve each child `parent_key` to `parent_id`.
4. Preserve level, rank, node membership, deterministic summary, and summary hash.
```

## GraphRAG Changes

GraphRAG keeps `RetrievalTrace.community_summaries` flat because Q&A, context packing, wiki payloads,
and diagnostics all consume it. Each item carries hierarchy fields:

```json
{
  "id": "repo:community:2:...",
  "name": "Context Budget Packing",
  "level": 2,
  "parent_id": "repo:community:1:...",
  "summary": "...",
  "node_count": 42,
  "matched_node_ids": ["..."]
}
```

Selection strategy:

1. Compute overlaps for all communities.
2. Prefer deepest matched leaves.
3. Add ancestors of selected leaves.
4. Limit siblings under the same parent.
5. Keep the total summary payload bounded.

Current prompt limits:

```text
MAX_COMMUNITY_SUMMARIES = 12
MAX_PARENT_SUMMARIES = 3
MAX_CHILD_SUMMARIES = 8
MAX_CHILDREN_PER_PARENT_IN_PROMPT = 4
```

`context_pack()` renders hierarchy visibly but compactly:

```text
Community Summaries:
[Architecture] Backend Analysis (repo:community:0:abc123): ...
  [Implementation] GraphRAG Retrieval (repo:community:1:def456): ...
  [Detail] Context Packing (repo:community:2:ghi789): ...
```

`RetrievalTrace.community_edges` is a compact filtered list for selected communities. It keeps only
fields useful for prompts and diagnostics:

```json
{
  "id": "repo:community-edge:...",
  "source": "repo:community:2:...",
  "target": "repo:community:2:...",
  "type": "calls_into",
  "confidence": 0.91,
  "reason": "Aggregated from 3 source graph edges: 3 calls."
}
```

`context_pack()` may render these as a small `Community Relationships` section. This is intentionally
separate from source-level `Graph Facts` so community inferences remain distinguishable.

## Wiki Generation Changes

Wiki prompts receive two community shapes:

- `community_summaries`: flat list with `level` and `parent_id`, shared with GraphRAG/Q&A.
- `community_hierarchy`: nested tree derived from the flat list, optimized for catalog planning.

The wiki payload also receives compact `community_edges` through `prompt_graph_facts(trace)`. These
relationships can guide architecture/data-flow prose, but they remain derived facts and should not be
used as file citations by themselves.

`prompt_graph_facts(trace)` intentionally keeps only fields needed for writing documentation:

- nodes: `id/type/name/file_path/line/hop/score/confidence`;
- source edges: `id/source/target/type/confidence/reason`;
- community edges: `id/source/target/type/confidence/reason`.

Full source chunk bodies are kept in `context_pack.text`; `source_chunks` carries metadata only to
avoid duplicating large code content.

## Mermaid Diagram Changes

`diagrams/rendering.py::_community_index()` indexes only one hierarchy level at a time. By default it
uses the deepest level available in the provided trace. This avoids grouping a node into overlapping
parent and child clusters.

Default behavior:

```text
If level=2 communities exist in the trace:
  index level=2 detail communities.
Else if level=1 communities exist:
  index level=1 implementation communities.
Else:
  index level=0 architecture communities.
```

Parent communities remain textual context unless a diagram explicitly chooses a high-level overview.

## API And Frontend Changes

`/graph` returns communities with hierarchy fields and returns `community_edges` alongside source
nodes and source edges.

Frontend behavior:

- overview mode shows `Architecture areas` for level 0;
- users can view `Implementation areas` and `Detailed areas` when present;
- graph builders render one hierarchy level at a time to avoid overlapping boxes;
- TypeScript types include `parent_id`, `rank`, and `GraphCommunityEdge`.

## Incremental Analysis

`IncrementalUpdater` uses the same analysis pipeline as full analysis, so community hierarchy and
community edges are rebuilt together after graph changes. Partial community patching is deliberately
avoided because parent `node_ids` and community edges are derived from the full current graph.

Incremental stats should include total community count and count by level, matching full analysis.

## Community Naming

LLM naming must not spend the entire budget on whichever rows happen to sort first. The naming target
selection is layer-aware:

```text
1. Select architecture parents first.
2. Select important implementation children by node/file size.
3. Select important detail communities by node/file size.
4. Respect the global max community naming cap.
```

Child/detail payloads include parent context:

```json
{
  "id": "...",
  "level": 2,
  "parent_id": "...",
  "parent_name": "GraphRAG Retrieval",
  "ancestor_names": ["Backend Analysis", "GraphRAG Retrieval"],
  "node_count": 42,
  "files": [],
  "symbols": []
}
```

Response application preserves `level`, `parent_id`, `rank`, `node_ids`, and `created_at`.

## Statistics

Analysis stats include both total communities and a compact level breakdown:

```json
{
  "community_count": 37,
  "community_count_by_level": {"0": 6, "1": 23, "2": 8}
}
```

The JSON object uses string keys for stable API serialization.

## Testing Plan

- Detector returns parent, child, and bounded detail communities for large synthetic graphs.
- Small graphs remain compact and do not emit low-signal detail communities.
- All retained children have valid parent IDs after record building.
- Community edges include `contains` and aggregated dependency relationships.
- GraphRAG selects deepest leaves, includes ancestors, filters community edges to selected IDs, and
  keeps prompt payload bounded.
- Wiki payloads include flat summaries, nested hierarchy, and compact community edges.
- Mermaid grouping indexes only the deepest available level by default.
- Naming payload includes parent context and target selection covers multiple levels.
- Full and incremental analysis stats include `community_count_by_level`.
- Frontend builds with hierarchy-aware community and edge types.

## Rollout Status

### Phase 1: Hierarchical Community Nodes

Implemented.

### Phase 2: Frontend Hierarchy UX

Implemented for level-specific overview modes and hierarchy-aware graph builders.

### Phase 3: Aggregated Community Edges

Implemented for persistence, API response, and compact GraphRAG/Wiki prompt payloads.

### Phase 4: Deeper Hierarchy

Implemented as bounded level-2 detail communities for oversized implementation areas.

## Remaining Gaps

- Continue evaluating whether community edges should directly drive additional server-generated
  wiki diagrams, beyond prompt facts and frontend/API exposure.
- Improve community naming quality with a parent-first then child/detail naming sequence if needed;
  the current implementation sends parent context but does not require two separate LLM rounds.
- Add quality metrics comparing flat, two-level, and detail-level retrieval token usage on large real
  repositories.

## Risks And Mitigations

| Risk | Mitigation |
| --- | --- |
| Too many communities increase prompt tokens | Deepest-leaf selection, ancestor caps, sibling caps |
| Parent and child overlap confuses diagrams/UI | Render one hierarchy level at a time |
| LLM naming focuses on broad parents only | Layer-aware target selection and parent context |
| Poor parent split biases wiki catalog | Treat communities as hints, not hard catalog structure |
| Community edge inference appears source-grounded | Keep community edges separate from `code_edge` and source citations |
| Detail splitting slows large analysis | Emit detail communities only past thresholds and caps |
