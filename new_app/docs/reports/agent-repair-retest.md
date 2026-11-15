# Agent 修复链路复测（重建镜像后，Qwen3.6-35B-A3B-NVFP4 @ 192.168.188.75:9988）

| 指标 | 修复前 | 修复后 |
|---|---|---|
| 闭环验证通过 | 0/13 | 0/13 |
| SANDBOX_RECIPE_CONFLICT | 5 | 0 |
| no-op 补丁被拦截 | 0 | 6 |
| 平均 patch op | 9.7 | 1.85 |
| 处理耗时 p50 / p95 | 25.6s / 79.0s | 10.9s / 78.9s |

- 状态分布：{"needs_more_info": 13}
- 结论：工程缺陷（版本冲突）已消除、no-op 补丁被拦截，时延 p50 下降 57%；仍未有一条进入 `verified`。剩余 5 条有 op 的样本验证结果为 `Target <rule>: not fixed; new errors=0`，`diff` 为空——补丁应用后记录完全没变化，说明模型仍在用"加绑定"解释表结构问题。

| # | rule_id | 修复前 | 修复后 | ops | 验证 passed | 耗时 |
|---|---|---|---|---|---|---|
| 1 | DOC-LOW-COVERAGE | needs_more_info | needs_more_info | 2 | False | 12.7s |
| 2 | DOC-LOW-COVERAGE | needs_more_info | needs_more_info | 7 | False | 5.0s |
| 3 | DOC-LOW-COVERAGE | needs_more_info | needs_more_info | 5 | False | 15.8s |
| 4 | DOC-NO-RECORDS | needs_more_info | needs_more_info | 0 | False | 8.0s |
| 5 | DOC-NO-RECORDS | needs_more_info | needs_more_info | 3 | False | 10.5s |
| 6 | DOC-NO-RECORDS | needs_more_info | needs_more_info | 0 | False | 106.7s |
| 7 | DOC-UNBOUND-COLUMNS | needs_more_info | needs_more_info | 0 | False | 78.9s |
| 8 | DOC-UNBOUND-COLUMNS | needs_more_info | needs_more_info | 0 | False | 68.8s |
| 9 | DOC-UNBOUND-COLUMNS | needs_more_info | needs_more_info | 5 | False | 13.8s |
| 10 | DOC-DUP-KEYS | needs_more_info | needs_more_info | 0 | False | 10.9s |
| 11 | DOC-DUP-KEYS | needs_more_info | needs_more_info | 2 | False | 10.6s |
| 12 | DOC-DUP-KEYS | needs_more_info | needs_more_info | 0 | None | 7.9s |
| 13 | DOC-NO-TABLES | needs_more_info | needs_more_info | 0 | None | 8.7s |
