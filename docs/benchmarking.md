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
Analyze commands are invoked with `--progress`, so Code Wiki also reports internal
progress such as scan counts, parse file counts, graph size, community counts,
and persistence stages. In an interactive terminal these updates refresh the same
status area instead of printing a long stream of progress rows: the first line
keeps the overall benchmark bar, the second line shows the current stage, and
the third line shows detailed context such as the current file path. Command
failures are printed in a separated error block so stderr does not run into the
progress display.

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
