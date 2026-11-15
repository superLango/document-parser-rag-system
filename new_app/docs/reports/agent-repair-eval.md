# Agent 修复能力量化（Qwen3.6-35B-A3B-NVFP4 @ 192.168.1.35:9988）

> 抽样方式：从 5475 条 open feedback 中按 rule_id 分层抽取 13 条，逐条调用
> `POST /v1/feedback/{id}/process`，统计 triage 质量、proposal 质量与闭环验证结果。

## 一、总体指标

| 指标 | 结果 | 说明 |
|---|---|---|
| LLM 真实推理占比 | **92.3%**（12/13） | 1 条返回 `unknown/0.5`，无兜底标记但信息不足 |
| triage 根因与规则标签一致率 | **92.3%**（12/13） | rule_id → 期望根因集合的映射判定 |
| proposal 生成率 | **84.6%**（11/13） | 平均 9.7 条 JSON Patch op |
| patch op 可执行率 | **14.0%**（15/107） | 目标配方 bindings 中不存在的新键 |
| patch op 冗余率 | **54.2%**（58/107） | 目标配方中已存在的键（重复添加） |
| patch op 其它路径 | 34/107 | `/bindings/row_key/-`、`/signature/tokens/-` 等追加型操作 |
| **闭环验证通过率** | **0.0%**（0/13） | `verification.passed` 全为 false |
| 处理耗时 p50 / p95 | 25.6s / 79.0s | 另有 1 条 206.1s 长尾 |
| 状态分布 | `needs_more_info` 13/13 | 无一条进入 `verified` |

## 二、逐条结果

| # | rule_id | 目标配方 | 根因 | 置信 | ops | 可用/冗余/其它 | 验证 | 失败原因 |
|---|---|---|---|---|---|---|---|---|
| 1 | DOC-LOW-COVERAGE | classification_v1 | recipe_binding | 0.90 | 10 | 10/0/0 | ✗ | 补丁应用成功但目标未修复 |
| 2 | DOC-LOW-COVERAGE | classification_v1 | recipe_binding | 0.90 | 7 | 1/0/6 | ✗ | 目标未修复 |
| 3 | DOC-LOW-COVERAGE | classification_v1 | table_structure | 0.85 | 5 | 0/0/5 | ✗ | 目标未修复 |
| 4 | DOC-NO-RECORDS | inspection_rules_v1 | recipe_binding | 0.90 | 5 | 2/0/3 | ✗ | 目标未修复 |
| 5 | DOC-NO-RECORDS | classification_v1 | recipe_binding | 0.95 | 4 | 0/3/1 | ✗ | 目标未修复 |
| 6 | DOC-NO-RECORDS | chemical_composition_v1 | recipe_binding | 0.95 | 40 | 0/40/0 | ✗ | 40 条全部重复绑定，未改变结果 |
| 7 | DOC-UNBOUND-COLUMNS | chemical_composition_v1 | recipe_binding | 0.95 | 14 | 0/7/7 | ✗ | `SANDBOX_RECIPE_CONFLICT` |
| 8 | DOC-UNBOUND-COLUMNS | chemical_composition_v1 | recipe_binding | 0.95 | 9 | 0/4/5 | ✗ | `SANDBOX_RECIPE_CONFLICT` |
| 9 | DOC-UNBOUND-COLUMNS | chemical_composition_v1 | recipe_binding | 0.95 | 8 | 0/4/4 | ✗ | `SANDBOX_RECIPE_CONFLICT` |
| 10 | DOC-DUP-KEYS | classification_v1 | recipe_binding | 0.85 | 3 | 1/0/2 | ✗ | `SANDBOX_RECIPE_CONFLICT` |
| 11 | DOC-DUP-KEYS | classification_v1 | table_structure | 0.85 | 2 | 1/0/1 | ✗ | `SANDBOX_RECIPE_CONFLICT` |
| 12 | DOC-DUP-KEYS | classification_v1 | recipe_binding | 0.85 | 0 | 0/0/0 | ✗ | 未产出补丁 |
| 13 | DOC-NO-TABLES | —（无 routing） | unknown | 0.50 | 0 | 0/0/0 | ✗ | 无可路由配方 |

## 三、失败归因

| 归因 | 数量 | 性质 |
|---|---|---|
| `SANDBOX_RECIPE_CONFLICT`（候选版本与该配方其它分表旧版本冲突） | 5 | **工程缺陷**，非模型能力问题；已在 `_override_assignments` 修复，待重建镜像后复测 |
| 补丁生效但"目标未修复"（多为重复添加已有绑定） | 5 | **模型能力问题**：把结构/OCR/覆盖问题误判为"缺绑定"，补丁是 no-op |
| 未产出补丁（1 条 206s 后空返回，1 条 unknown） | 2 | 模型长尾/证据不足 |
| 无 routing 配方 | 1 | 数据前提缺失 |

## 四、结论

1. **定位能力达标**：92% 的 triage 使用了真实 LLM 推理，根因与规则语义一致，证据引用具体诊断码。
2. **补丁生成能力基本达标**：85% 能产出结构化 JSON Patch。
3. **补丁有效性不达标**：0/13 通过闭环验证；其中 54% 的操作是重复添加配方已有的绑定，属于 no-op。
4. **验证链路本身有 bug**：5/13 因 `SANDBOX_RECIPE_CONFLICT` 无法进入验证，已修复。
5. 因此当前 agent 的角色是"能诊断、能出草案"，**不能自动修复**；在 verify 前应增加 no-op 补丁拦截与诊断上下文增强。

## 五、复测计划

1. 重建镜像（含 `_override_assignments` 修复）
2. 对同一批 feedback 重跑，预期验证通过率仍低（补丁冗余问题需提示词/规则配合）
3. 增强项：
   - proposal 生成前过滤已存在路径，空补丁直接回退 `needs_more_info`
   - triage/repair prompt 注入表格表头与 `MEASURE_COLUMN_MISSING` 明细，避免"缺列=缺绑定"误判

## 六、已实施的增强（待重建镜像后生效）

| 改动 | 位置 | 作用 |
|---|---|---|
| no-op 补丁过滤 | `services/agent/agents/repair.py` `_is_redundant` / `_filtered_fallback` | `add`/`replace` 的路径与值均已存在、或 `/-` 追加的 token 已在数组内时丢弃；过滤后无有效 op 直接返回 `needs_human`，不再进入沙箱验证 |
| 规则兜底同样过滤 | 同上 `_filtered_fallback` | 兜底补丁不会重复添加已有绑定 |
| 诊断带上表头 | `services/sandbox/runtime/builtin.py` `MEASURE_COLUMN_MISSING` | `detail` 增加 `headers` 与 `bound_measures`，可区分"缺列"与"缺绑定" |
| repair 上下文注入 | `services/orchestration/feedback/service.py` `_repair` | 只传目标表的诊断（≤20 条）+ 表摘要，避免长文档诊断淹没证据 |
| triage 上下文 | 同上 `_context` | `run_summary.table` 带目标表摘要，诊断里已有 headers |
| prompt 更新 | `prompts/repair.v1.txt` / `prompts/triage.v1.txt` | 明确"已有绑定不得重复添加"、"headers 无可用列时不是 recipe_binding" |

测试：`tests/integration/agent` 90 项通过，`tests/integration/sandbox` 全通过。

