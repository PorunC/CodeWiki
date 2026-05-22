# CodeWiki 压测报告 2026-05-22

## 摘要

本轮压测验证了 CodeWiki 在 S/M 级真实仓库上的 cold analyze 能力。已完成结果覆盖
`facebook/react` 和 `microsoft/vscode` 的冷启动全量分析。

最新有效结果显示：

- React cold analyze：31.807s，扫描 6,784 个文件，解析 4,376 个文件，生成 23,574 个节点和 125,306 条边。
- VS Code cold analyze：569.516s，扫描 13,985 个文件，解析 10,537 个文件，生成 169,859 个节点和 3,804,028 条边。
- VS Code 数据库最终体积约 9.8 GiB，边数量和 SQLite 写入规模是主要压力来源。
- 旧实现曾在 persist 阶段形成超大 WAL 和长事务；已提交 `e7f1c6c` 将主要批量写入改为 500 条一批提交，并在 benchmark heartbeat 中展示数据库行数。

## 测试环境与命令

工作区：

```bash
/Users/misaka/Downloads/Code/CodeWiki
```

结果目录：

```bash
/Users/misaka/CodeWikiBench/results/
```

主要命令：

```bash
.venv/bin/python scripts/benchmark_repos.py --repos vscode prepare
.venv/bin/python scripts/benchmark_repos.py --repos vscode run --scenarios cold
```

当前有效结果文件：

```bash
/Users/misaka/CodeWikiBench/results/20260522T020001Z/summary.csv
/Users/misaka/CodeWikiBench/results/20260522T025833Z/summary.csv
/Users/misaka/CodeWikiBench/results/20260522T033044Z/summary.csv
```

## 结果总览

| Run ID | 仓库 | 场景 | 耗时 | 状态 | 扫描文件 | 解析文件 | 节点 | 边 | 社区 | 错误 |
| --- | --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 20260522T020001Z | facebook/react | cold | 38.821s | 成功 | 6,784 | 4,376 | 23,574 | 125,306 | 128 | 0 |
| 20260522T025833Z | facebook/react | cold | 31.807s | 成功 | 6,784 | 4,376 | 23,574 | 125,306 | 128 | 0 |
| 20260522T033044Z | microsoft/vscode | cold | 569.516s | 成功 | 13,985 | 10,537 | 169,859 | 3,804,028 | 128 | 4 |

React 两次 cold 的结果结构一致，第二轮耗时降低约 18.1%。VS Code cold 成功完成，
耗时约 9.49 分钟。

## 数据库写入规模

| 数据库 | 体积 | repo | analysis_run | code_node | code_edge | graph_community | graph_community_edge |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| react 20260522T020001Z | 208 MiB | 1 | 1 | 23,574 | 125,306 | 128 | 701 |
| react 20260522T025833Z | 208 MiB | 1 | 1 | 23,574 | 125,306 | 128 | 690 |
| vscode 20260522T033044Z | 9.8 GiB | 1 | 1 | 169,859 | 3,804,028 | 128 | 1,081 |

VS Code 的 `code_edge` 达到 3,804,028 条，数据库体积约 9.8 GiB，平均每 1,000 个节点约
59.7 MiB。相比 React 的约 8.8 MiB/千节点，VS Code 的边密度和索引写入成本明显更高。

## 吞吐估算

| 仓库 | 场景 | 解析文件/s | 节点/s | 边/s |
| --- | --- | ---: | ---: | ---: |
| facebook/react 20260522T020001Z | cold | 112.7 | 607.2 | 3,227.8 |
| facebook/react 20260522T025833Z | cold | 137.6 | 741.2 | 3,939.6 |
| microsoft/vscode 20260522T033044Z | cold | 18.5 | 298.3 | 6,679.4 |

VS Code 的文件解析吞吐显著低于 React，但边写入吞吐更高，说明主要压力不只来自文件数，
还来自更大的符号图和 SQLite B-tree/FTS 写入成本。

## 观察到的问题

1. 旧实现的 persist 阶段存在超大事务风险。
   在 VS Code cold 运行中，主库一度仍很小，但 WAL 文件增长到 8 GiB 以上，外部查询只能看到
   `repo=1` 和 `analysis_run=1`，说明大量写入尚未 commit/checkpoint。

2. benchmark 进度可观测性不足。
   原先 heartbeat 只能看到 elapsed，无法判断数据库是否仍在写入。现在脚本会展示数据库总行数和
   主要表计数，下一次运行可直接看到 persist 阶段的写入推进。

3. VS Code 解析有 4 个预期内源码错误。
   错误来自测试 fixture 或兼容性用例，例如 Python 语法错误、坏 token、Python 2 print 语法等。
   cold analyze 最终成功，错误数量为 4。

## 已完成改动

提交 `e7f1c6c fix(backend): batch sqlite benchmark writes` 完成了两类改动：

- 将 graph、chunk、community、embedding 等主要批量写入路径改为 500 条一批提交。
- 批量插入路径使用 SQLite ignore/upsert 语义，降低重复插入和长事务风险。
- benchmark heartbeat 读取 SQLite 计数，展示当前写入总行数及 nodes、edges、chunks、communities 等拆分。

已验证：

```bash
python -m py_compile scripts/benchmark_repos.py
.venv/bin/ruff check scripts/benchmark_repos.py
.venv/bin/ruff check backend/app/db/repositories/code_graph.py backend/app/db/repositories/code_chunks.py backend/app/db/repositories/communities.py backend/app/db/repositories/embeddings.py
.venv/bin/pytest -q tests/backend/test_database_schema.py::test_graphrag_wiki_and_llm_records_round_trip tests/backend/test_database_schema.py::test_replace_graph_deletes_stale_nodes_in_batches tests/backend/test_graph_rag.py tests/backend/test_community_namer.py
```

## 建议

下一轮 VS Code cold 压测可重新跑：

```bash
.venv/bin/python scripts/benchmark_repos.py --repos vscode run --scenarios cold
```

重点观察：

- `detail:` 中数据库行数是否按 500 条批次持续增长。
- WAL 是否不再长时间堆积到多 GiB 才一次性可见。

如果 VS Code 仍有明显持久化瓶颈，下一步应优先分析 `code_edge` 生成规模和索引策略，因为
3.8M 条边是当前最大写入面。
