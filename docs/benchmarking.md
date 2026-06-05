# Code Wiki layered benchmark guide

This benchmark plan uses progressively larger repositories so we can capture
cold, warm, and small-delta behavior before moving into XL stress tests.

## Default baseline

`scripts/benchmark_repos.py run` defaults to this order:

1. `facebook/react`
2. `microsoft/vscode`
3. `apache/superset`
4. `kubernetes/kubernetes`
5. `elastic/elasticsearch`

The default scenarios are:

- `cold`: fresh SQLite database, forced graph rebuild.
- `warm`: same database, unchanged follow-up analyze.
- `small-delta`: add one tiny source file, run incremental update, then remove the file.

The script records JSONL details and a CSV summary under:

```bash
~/CodeWikiBench/results/<timestamp>/
```

During long runs it uses `tqdm` progress bars and prints per-step status lines
for the active clone/analyze/update command.
For long analyze/update commands, the runner also emits periodic heartbeats like
`RUNNING vscode:warm elapsed 35m12s`; tune the interval with `--status-interval`.
Analyze commands still pass the legacy `--progress` flag so older benchmark
commands remain accepted by the TypeScript CLI. The runner prints periodic
heartbeats for long commands; richer internal stage progress is a future TS
backend follow-up. Command failures are printed in a separated error block so
stderr does not run into the progress display.

## Prepare repositories

Clone the recommended non-XL sample set with shallow history:

```bash
python scripts/benchmark_repos.py prepare
```

This includes the default baseline set plus `rust-lang/rust` and
`nrwl/large-ts-monorepo`. Existing clones are skipped. Every clone command uses
`git clone --depth 1 --progress`, so Git prints transfer progress and download
speed while repositories are being fetched.

## Run the first baseline

```bash
python scripts/benchmark_repos.py run
```

To run only the first S-sized baseline:

```bash
python scripts/benchmark_repos.py --repos react run
```

To use a shorter timeout while shaking out local failures:

```bash
python scripts/benchmark_repos.py run --timeout-minutes 30
```

## Expand cautiously

Run Rust after the default baseline is stable:

```bash
python scripts/benchmark_repos.py --repos rust run
```

Run a benchmark/research repository explicitly:

```bash
python scripts/benchmark_repos.py --repos large-ts-monorepo run
```

XL repositories are blocked unless acknowledged:

```bash
python scripts/benchmark_repos.py --repos nixpkgs --yes-xl prepare
python scripts/benchmark_repos.py --repos nixpkgs --yes-xl run --timeout-minutes 240
```

## Inspect the manifest

```bash
python scripts/benchmark_repos.py list
```

Use the listed `key` values with `--repos`.

## Lite Mode stress test

Lite Mode has a separate synthetic stress runner because it focuses on project-local
agent workflows rather than full Wiki/GraphRAG generation. The runner generates a
Python repository with configurable module count and call fanout, then measures:

- cold `codewiki lite index`
- `status`, `query`, `context`, `trace`, `node`, and indexed `files`
- stale `affected` and `status`
- incremental `sync` and fresh `status`

```bash
python scripts/benchmark_lite_mode.py --files 600 --fanout 3
```

Results are written under:

```bash
~/CodeWikiLiteBench/results/<timestamp>/
```

Use a larger module count for heavier local stress runs:

```bash
python scripts/benchmark_lite_mode.py --files 2000 --fanout 4 --timeout-seconds 900
```

Both benchmark scripts run the local TypeScript backend through
`npm --prefix backend exec -- tsx -- src/cli.ts`. Set `CODEWIKI_CLI` to a
shell-style command, such as `node backend/dist/cli.js`, to benchmark a built
or globally installed CLI instead.
