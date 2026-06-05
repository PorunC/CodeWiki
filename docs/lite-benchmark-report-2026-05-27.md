# CodeWiki Lite Mode stress report 2026-05-27

## Summary

This run used the synthetic Lite Mode stress runner to exercise the project-local,
no-LLM agent index path. The runner generated Python repositories with many small
modules and explicit call/import fanout, then measured indexing, freshness checks,
symbol search, context building, trace, node reads, indexed file reads, affected-file
analysis, and incremental sync.

Result files:

```bash
/Users/misaka/CodeWikiLiteBench/results/20260527T062821Z/
/Users/misaka/CodeWikiLiteBench/results/20260527T063913Z/
```

The larger validated run used 2,000 generated modules with fanout 4. It produced
4,007 graph nodes and 24,010 graph edges. All Lite Mode commands exited with code 0.

## Commands

```bash
.venv/bin/python scripts/benchmark_lite_mode.py --files 600 --fanout 3 --timeout-seconds 300
.venv/bin/python scripts/benchmark_lite_mode.py --files 2000 --fanout 4 --timeout-seconds 900
```

## Results

| Scenario | 600 files / fanout 3 | 2,000 files / fanout 4 |
| --- | ---: | ---: |
| cold-index | 1.693s | 3.132s |
| warm-status | 0.978s | 2.106s |
| query | 0.338s | 0.382s |
| context | 0.455s | 0.800s |
| trace | 0.467s | 0.748s |
| node | 0.701s | 1.480s |
| files-index | 0.491s | 0.775s |
| affected | 0.522s | 0.740s |
| stale-status | 0.896s | 2.123s |
| sync | 1.028s | 2.909s |
| fresh-status | 0.893s | 2.110s |

## Larger run details

| Metric | Value |
| --- | ---: |
| Generated modules | 2,000 |
| Generated fanout | 4 |
| Scanned files | 2,003 |
| Parsed files on cold index | 2,002 |
| Parsed files on small-delta sync | 1 |
| Nodes | 4,007 |
| Edges | 24,010 |
| Files in index | 2,003 |
| Pending files before sync | 1 |
| Pending files after sync | 0 |

Edge distribution after cold index and after small-delta sync matched:

| Edge type | Count |
| --- | ---: |
| calls | 8,001 |
| contains | 4,006 |
| defines | 2,001 |
| exports | 2,001 |
| imports | 8,001 |

## Findings

- Lite Mode command latency stayed low on the synthetic 2,000-module repository:
  search, context, trace, affected analysis, and indexed file reads all completed
  under 1s, while node context completed in 1.480s.
- Cold indexing the 2,000-module synthetic repository took 3.132s and incremental
  sync after a one-file delta took 2.909s.
- The first 2,000-module stress run exposed an incremental containment regression:
  file-to-symbol `contains` edges were lost for reused files after sync. The legacy
  fix prevented recovered symbols from treating file nodes as symbol parents, so
  GraphBuilder correctly fell back to file containment. The rerun confirmed stable
  edge counts before and after sync.

## Follow-ups

- Add a real-repository Lite Mode benchmark arm once representative local clones are
  available, so synthetic results can be compared with large TypeScript/Python/Go
  repositories.
- Break out command timing inside `codewiki_context` and `codewiki_node` to separate
  graph expansion, source section reading, and JSON serialization cost.
- Consider an optional benchmark mode that keeps the generated repository and lite DB
  for SQLite table-size inspection.
