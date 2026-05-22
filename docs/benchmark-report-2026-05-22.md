# CodeWiki 压测报告 2026-05-22

## 摘要

本轮压测使用 `/home/misaka/CodeWikiBench` 下的真实仓库与结果文件，覆盖 M/L 级仓库的
cold、warm、small-delta 三类场景。最新有效结果位于：

```bash
/home/misaka/CodeWikiBench/results/20260522T101045Z/
/home/misaka/CodeWikiBench/results/20260522T103223Z/
/home/misaka/CodeWikiBench/results/20260522T105847Z/
```

核心结论：

- `rust-lang/rust` L 级仓库 cold analyze 成功完成，耗时 318.553s，扫描 58,260 个文件，解析 36,220 个文件，生成 308,821 个节点和 886,546 条边。
- `microsoft/vscode` M 级仓库 cold analyze 成功完成，耗时 547.184s，扫描 14,048 个文件，解析 10,507 个文件，生成 169,492 个节点和 3,793,136 条边。
- `apache/superset` M 级仓库 cold analyze 成功完成，耗时 105.021s，扫描 8,803 个文件，解析 5,672 个文件，生成 40,621 个节点和 476,166 条边。
- warm 与 small-delta 均可进入 incremental 模式，并复用 96.9% 至 99.7% 的扫描文件；但 VS Code 与 Rust 的增量场景仍需要重建大规模图与社区，端到端耗时下降有限。
- 本轮只有 VS Code cold 出现 4 个源码解析错误，均来自仓库内测试 fixture 或兼容性用例；所有场景最终退出码均为 0。

## 测试环境与命令

工作区：

```bash
/home/misaka/project-wiki/code-wiki
```

压测仓库与结果目录：

```bash
/home/misaka/CodeWikiBench/
/home/misaka/CodeWikiBench/results/
```

主要命令形态：

```bash
.venv/bin/python scripts/benchmark_repos.py --repos rust run
.venv/bin/python scripts/benchmark_repos.py --repos vscode run
.venv/bin/python scripts/benchmark_repos.py --repos superset run
```

本次报告读取的结果文件：

```bash
/home/misaka/CodeWikiBench/results/20260522T101045Z/summary.csv
/home/misaka/CodeWikiBench/results/20260522T103223Z/summary.csv
/home/misaka/CodeWikiBench/results/20260522T105847Z/summary.csv
```

## 结果总览

| Run ID | 仓库 | 级别 | 场景 | 模式 | 耗时 | 状态 | 扫描文件 | 解析文件 | 复用文件 | 节点 | 边 | 社区 | 错误 |
| --- | --- | --- | --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 20260522T101045Z | rust-lang/rust | L | cold | full | 318.553s | 成功 | 58,260 | 36,220 | 0 | 308,821 | 886,546 | 128 | 0 |
| 20260522T101045Z | rust-lang/rust | L | warm | incremental | 247.087s | 成功 | 58,260 | 6 | 58,075 | 308,814 | 702,887 | 128 | 0 |
| 20260522T101045Z | rust-lang/rust | L | small-delta | incremental | 258.086s | 成功 | 58,261 | 7 | 58,075 | 308,815 | 883,065 | 128 | 0 |
| 20260522T103223Z | microsoft/vscode | M | cold | full | 547.184s | 成功 | 14,048 | 10,507 | 0 | 169,492 | 3,793,136 | 128 | 4 |
| 20260522T103223Z | microsoft/vscode | M | warm | incremental | 514.561s | 成功 | 14,048 | 30 | 13,615 | 169,252 | 1,987,222 | 128 | 0 |
| 20260522T103223Z | microsoft/vscode | M | small-delta | incremental | 388.219s | 成功 | 14,049 | 31 | 13,615 | 169,253 | 2,045,949 | 128 | 0 |
| 20260522T105847Z | apache/superset | M | cold | full | 105.021s | 成功 | 8,803 | 5,672 | 0 | 40,621 | 476,166 | 128 | 0 |
| 20260522T105847Z | apache/superset | M | warm | incremental | 69.533s | 成功 | 8,803 | 20 | 8,646 | 40,609 | 215,109 | 128 | 0 |
| 20260522T105847Z | apache/superset | M | small-delta | incremental | 64.521s | 成功 | 8,804 | 21 | 8,646 | 40,610 | 234,156 | 128 | 0 |

## 增量效果

| 仓库 | warm 复用率 | warm 相对 cold 提速 | small-delta 复用率 | small-delta 相对 cold 提速 |
| --- | ---: | ---: | ---: | ---: |
| rust-lang/rust | 99.7% | 1.29x | 99.7% | 1.23x |
| microsoft/vscode | 96.9% | 1.06x | 96.9% | 1.41x |
| apache/superset | 98.2% | 1.51x | 98.2% | 1.63x |

Superset 的增量收益最明显，warm 与 small-delta 均降到 70s 以下。Rust 虽然只重新解析 6 到 7 个文件，
但最终节点仍超过 30 万，small-delta 边数接近 cold，因此图构建、社区发现与持久化仍占据主要成本。
VS Code warm 只比 cold 快约 6.3%，说明对于边密度很高的仓库，减少解析文件数不足以显著降低端到端耗时。

## 吞吐估算

| 仓库 | 场景 | 解析文件/s | 节点/s | 边/s |
| --- | --- | ---: | ---: | ---: |
| rust-lang/rust | cold | 113.7 | 969.4 | 2,783.0 |
| rust-lang/rust | warm | 0.0 | 1,249.8 | 2,844.7 |
| rust-lang/rust | small-delta | 0.0 | 1,196.6 | 3,421.6 |
| microsoft/vscode | cold | 19.2 | 309.8 | 6,932.1 |
| microsoft/vscode | warm | 0.1 | 328.9 | 3,862.0 |
| microsoft/vscode | small-delta | 0.1 | 436.0 | 5,270.1 |
| apache/superset | cold | 54.0 | 386.8 | 4,534.0 |
| apache/superset | warm | 0.3 | 584.0 | 3,093.6 |
| apache/superset | small-delta | 0.3 | 629.4 | 3,629.1 |

warm 与 small-delta 的解析文件/s 仅用于说明实际重新解析量很小，不代表解析器自身吞吐下降。
这些场景的端到端时间主要花在复用符号后的图重建、社区计算和 SQLite 写入。

## 数据库写入规模

本轮结果目录中只有 Rust run 保留了 SQLite 数据库文件：

| 数据库 | 体积 | repo | analysis_run | code_node | code_edge | graph_community | graph_community_edge | code_chunk |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| rust 20260522T101045Z | 1.3 GiB | 1 | 3 | 308,815 | 883,065 | 128 | 276 | 0 |

VS Code 与 Superset 的 `results.jsonl` 中记录了对应的 `db_url`，但结果目录下未保留
`vscode.sqlite3` 和 `superset.sqlite3` 文件，因此本报告只列出 summary 中的节点、边和社区规模。

## 观察到的问题

1. 增量路径仍会承担较重的图级成本。
   Rust warm 复用 58,075 个文件且只解析 6 个文件，但仍耗时 247.087s；VS Code warm 复用 13,615 个文件，
   但耗时仍有 514.561s。后续优化重点应放在增量图构建、社区计算和持久化差量写入，而不只是文件解析复用。
2. VS Code 的边密度仍是主要压力源。
   VS Code cold 生成 3,793,136 条边，约为 Rust cold 的 4.28 倍、Superset cold 的 7.97 倍；即使节点数少于 Rust，
   总耗时仍更长。
3. VS Code cold 有 4 个预期内源码解析错误。
   错误来自 Python 测试 fixture 或兼容性用例，包括缺少冒号、不可打印字符、坏转义和 Python 2 `print` 语法。
   该 run 最终状态为成功，退出码为 0。
4. 结果归档不完整。
   Rust 保留了 sqlite 数据库，可做表级计数；VS Code 和 Superset 仅保留 `summary.csv` 与 `results.jsonl`，
   无法复核最终 SQLite 文件体积和表级写入规模。

## 与旧结果的关系

旧报告记录过 React 和一次 VS Code cold 结果：

| Run ID | 仓库 | 场景 | 耗时 | 扫描文件 | 解析文件 | 节点 | 边 | 错误 |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 20260522T020001Z | facebook/react | cold | 38.821s | 6,784 | 4,376 | 23,574 | 125,306 | 0 |
| 20260522T025833Z | facebook/react | cold | 31.807s | 6,784 | 4,376 | 23,574 | 125,306 | 0 |
| 20260522T033044Z | microsoft/vscode | cold | 569.516s | 13,985 | 10,537 | 169,859 | 3,804,028 | 4 |

新的 VS Code cold 结果为 547.184s，较旧 run 的 569.516s 快约 3.9%，节点和边规模基本一致。

## 建议

- 优先优化增量图构建和社区计算，目标是让 warm/small-delta 的端到端时间更接近实际变更文件规模。
- 将 benchmark runner 的结果归档调整为默认保留 sqlite 文件或输出表级计数，避免后续报告只能依赖 summary。
- 对 VS Code 这类高边密度仓库继续拆分 `code_edge` 写入与索引成本，评估是否需要边去重、延迟索引或按边类型分批持久化。
- 下一轮建议补跑 `kubernetes`、`elasticsearch` 和 `large-ts-monorepo`，形成 M/L/XL 梯度对比。
