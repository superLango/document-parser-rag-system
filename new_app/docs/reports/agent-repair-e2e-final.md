# Agent 修复闭环端到端复测（Stage 0-5，13 条真实 feedback）

| 指标 | 旧链路 | 新闭环 |
|---|---|---|
| 闭环验证通过 | 0/13 | 4/13 |
| 自动生效（auto） | 0 | 8 |
| 待复审（review） | 0 | 3 |
| L1 表修复尝试 | 0 | 7 |
| 平均 patch op | 1.85 | 4.31 |
| 耗时 p50 / p95 | 10.9s / 78.9s | 17.1s / 21.7s |

- 状态分布：{"verified": 4, "needs_more_info": 9}

| # | rule_id | 旧状态 | 新状态 | scope | ops | 门禁 | tier | 耗时 |
|---|---|---|---|---|---|---|---|---|
| 1 | DOC-LOW-COVERAGE | needs_more_info | verified | data | 0 | accept | auto | 13.8s |
| 2 | DOC-LOW-COVERAGE | needs_more_info | needs_more_info | data | 0 | rollback | auto | 21.7s |
| 3 | DOC-LOW-COVERAGE | needs_more_info | needs_more_info | data | 0 | rollback | auto | 17.1s |
| 4 | DOC-NO-RECORDS | needs_more_info | needs_more_info | data | 0 | rollback | auto | 14.3s |
| 5 | DOC-NO-RECORDS | needs_more_info | needs_more_info | data | 0 | rollback | auto | 15.2s |
| 6 | DOC-NO-RECORDS | needs_more_info | needs_more_info | data | 0 | rollback | auto | 117.0s |
| 7 | DOC-UNBOUND-COLUMNS | needs_more_info | needs_more_info | data | 0 | rollback | auto | 13.7s |
| 8 | DOC-UNBOUND-COLUMNS | needs_more_info | needs_more_info | data | 0 | rollback | auto | 20.3s |
| 9 | DOC-UNBOUND-COLUMNS | needs_more_info | needs_more_info | recipe | 5 |  |  | 5.8s |
| 10 | DOC-DUP-KEYS | needs_more_info | verified | recipe | 17 | accept | review | 19.7s |
| 11 | DOC-DUP-KEYS | needs_more_info | verified | recipe | 17 | accept | review | 20.3s |
| 12 | DOC-DUP-KEYS | needs_more_info | verified | recipe | 17 | accept | review | 19.7s |
| 13 | DOC-NO-TABLES | needs_more_info | needs_more_info | engine | 0 | None | None | 3.6s |

## 第三轮：Stage 6 回灌 + 路由/spec 容错（当前代码）

复测方式：第二轮全量 13 条 → 仅重跑 8 条未通过项 → 仅重跑受修复影响的 5 条；4 条 verified 未改动。

| 指标 | 第一轮 | 第二轮 | 第三轮（当前） |
|---|---|---|---|
| verified | 4/13 | 4/13 | 4/13 |
| L1 尝试 | 7 | 3 | 5 |
| L1 rollback | 6 | 2 | 3 |
| 验证前终止 | 0 | 4 | 5 |

> 第三轮 L1 尝试增加，是因为 `replace_rows` 数组容错让 d4814744 首次通过 spec 校验进入沙箱验证，属于机制修复而非回归。

### 本轮生效的修复

1. repair 任务上下文从 146 KB 降到 38 KB（目标表全量行 + 其它表仅元数据；merges 只保留表头区 ≤40 条），消除了模型 400。
2. `history.previous_attempts` 回灌 coverage 差分与行级诊断；日志确认第二轮 prompt_tokens 上升（8747→9658、7186→7751），补丁随之调整。
3. `MEASURE_COLUMN_MISSING` 的 `detail.measure` 并入 `unbound_columns`，DOC-UNBOUND-COLUMNS 从 data 路由到 recipe。
4. 兼容 `replace_rows: [{"row_index":1,"cells":[...]}]`、扁平 `table_repair.spec`、一层嵌套 proposal；`scope=data` 但只有配方 ops 时按 recipe 处理。

### 仍未通过的根因

| 案例 | 现象 | 根因 |
|---|---|---|
| T4 / T5 / T1（3 条 rollback） | L1 补丁通过校验，重跑后 complete_rows 仍为 0 | 表头/行键修复未命中真实结构；T7 重跑后仍有 112 `EMPTY_RECORD_SKIPPED`、42 `STRATEGY_MISS`、7 `ROW_KEY_NOT_FOUND` |
| 3 条 DOC-UNBOUND-COLUMNS | 已路由到 recipe，但模型给出的 Ag/As 绑定与现有配方重复，判为 no-op | 配方已绑定这些元素，真实问题是表头/列缺失，应走表结构修复而非绑定 |
| 9f317d9f | 模型输出 `scope=data` + 空 patch，回退 needs_human | 模型未给出可验证补丁 |
| 2d0884c6 | DOC-NO-TABLES | OCR/版面问题，确定性不可自动修复 |

### 结论

Stage 6 回灌链路已闭环且可观测（coverage 前后值、resolved/still_missing、ROW_SKIPPED 行号均进入第二轮）。剩余失败集中在**表结构修复能力**与**目标表/行键选择**，不再是“模型不知道缺哪个字段”。

