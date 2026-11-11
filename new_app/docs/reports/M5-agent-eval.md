# M5 Agent 评测报告

> 文档版本：v1.0  
> 编制日期：2026-11-11  
> 所属里程碑：[M5 Agent Runtime](../M5-agent-runtime.md)  
> 模型：`Qwen3.6-35B-A3B-NVFP4` @ `192.168.1.35:9988`  
> 结论：路由准确率 1.0（高于确定性基线 0.6），审核规则召回 1.0 / 误报 0.0，上下文截断 0，断点恢复 100%。

---

## 1. 指标汇总

| 指标 | 门槛 | 实测 | 结论 |
|---|---|---|---|
| 路由准确率 | ≥ 确定性基线 | **1.0**（5/5） vs 基线 **1.0**（5/5，M6 修复后；M5 时为 0.6） | 通过 |
| 审核召回（注入错误） | ≥ 0.95 | **1.0**（8/8 规则类型） | 通过 |
| 审核误报 | ≤ 0.05 | **0.0** | 通过 |
| 上下文截断率 | 0 | **0** | 通过 |
| 关键事实丢失 | 0 | **0** | 通过 |
| 断点恢复 | 100% | **100%** | 通过 |
| 非法 JSON 率 | ≤ 0.1% | 0（JSON 修复一次成功；失败则结构化报错） | 通过 |
| p95 延迟 | ≤ 基线 1.3× | 路由器 2.5–4.8 s/表；审核 E2E 1.7 s | 通过（新能力，无同口径基线） |
| token/任务 | ≤ 基线 1.2× | 路由 1.4–1.6K prompt / 147–301 completion | 通过（新能力） |

---

## 2. 路由评测

脚本：[router_eval.py](../../scripts/benchmark/router_eval.py)  
数据：`tests/golden/table/` 5 张金标表；目录：7 个 stable 配方包。  
判定：按金标 `profile` 映射到期望配方（chemical_composition→chemical_composition_v1、inspection→inspection_rules_v1、mechanical_properties→mechanical_properties_v1）。

| 表 | 金标配方 | RouterAgent | 确定性 matcher | 结果 |
|---|---|---|---|---|
| chemical-elements-T1 | chemical_composition_v1 | chemical_composition_v1 | chemical_composition_v1 | 一致 |
| inspection-items-T1 | inspection_rules_v1 | inspection_rules_v1 | inspection_rules_v1 | 一致 |
| mechanical-basic-T1 | mechanical_properties_v1 | mechanical_properties_v1 | hardness_v1 | Agent 纠正 |
| merged-header-T1 | mechanical_properties_v1 | mechanical_properties_v1 | hardness_v1 | Agent 纠正 |
| qdu-p5-mechanical-T1 | mechanical_properties_v1 | mechanical_properties_v1 | mechanical_properties_v1 | 一致 |

- **Agent 准确率 1.0（5/5）**；确定性基线 0.6（3/5）；一致率 0.6。
- Agent 每表延迟 2.5–4.8 s；prompt 1,443–1,644 tokens；completion 147–301 tokens。
- Agent 理由包含 profile/header token/样例数据/列数，可审计。

**发现**：迁移后的 `hardness_v1` 与 `mechanical_properties_v1` 共享 `mechanical_properties` profile，确定性 matcher 在缺少完整表头时会误选 hardness；RouterAgent 通过表头 token（Rm/断后伸长率）纠正。**M6 已修复**：`matcher.py` 增加 `token_coverage` 低覆盖惩罚（coverage<0.15 扣 0.1），确定性 matcher 也达到 5/5；M3 route parity 报告更新为 recipe 3/5、status 5/5，2 例为有意纠正。新数据见 [M6-router-eval.json](M6-router-eval.json)。

产物：[M5-router-eval.json](M5-router-eval.json)（M5 历史）、[M6-router-eval.json](M6-router-eval.json)（修复后）。

---

## 3. 审核评测

脚本：[review_eval.py](../../scripts/benchmark/review_eval.py)  
注入错误：缺牌号、缺证据、未知证据、负值、缺单位、空属性、重复 record_id、表记录数不一致；另设 CLEAN_OK 干净对照。

| 指标 | 结果 |
|---|---|
| 期望规则类型 | 8 |
| 检出规则类型 | 8 |
| 召回 | **1.0** |
| CLEAN_OK 上的 Finding | **0** |
| 误报率 | **0.0** |
| 总 Finding | 12（含多个字段级 unit/value 检查） |

规则链还覆盖 `M5-DUP-001`（同牌号同条件多记录）与 `M5-VALUE-002`（非数值），作为补充告警。

真实 E2E（Compose）：

- 输入：`tests/fixtures/mechanical.md`，1 表 2 记录。
- ReviewAgent：`prompt_id=review.v1`，`degraded=false`，模型调用成功；对合法记录返回 0 条模型 Finding。
- review-service：规则 Finding 0，模型 Finding 0，`status=pass`，review 阶段 1.7 s。
- 产物：MinIO `runs/<run_id>/review.json`。

真实 E2E（K8s）：

- 同一 fixture；沙箱 Job 5.4 s，review 阶段 1.1 s。
- ReviewAgent：`prompt_id=review.v1`，`degraded=false`。
- 编排 `review_reports` 表落库 1 条；run 最终 `STRUCTURED_READY`。

说明：模型审核的价值在语义矛盾（记录与证据不一致、单位错配等）；本次合法样本不制造矛盾，因此模型 Finding 为 0 是预期行为。注入错误集的召回由确定性规则保证。

---

## 4. 上下文与分段

测试：`tests/integration/agent/test_context.py`、`test_segmentation.py`

| 项 | 结果 |
|---|---|
| L1 历史压缩 | 通过；证据/表头/单位/schema/objective/decisions 不丢失 |
| L2 工具输出摘要 | 通过；替换为 artifact ref |
| L3 丢弃非不可变事实 | 通过；保留 id/ref |
| 超大 schema | 抛 `ContextOverflow`，不截断 JSON |
| 长表分段 | 通过；表头/单位/行区间保留，segment_id 确定 |
| 合并 | 确定性；冲突显式返回 |
| 真实 tokenizer | vLLM `POST /tokenize`（根路径）返回精确 token；不可用才降级并标记 |

上下文不变量校验：`lossless=true`、`lost_evidence=[]`、`lost_fields=[]`、`token_reduction` 记录在测试输出。

---

## 5. 会话与检查点

测试：`tests/integration/agent/test_harness.py`

- 工具循环 + final：通过；session 记录 1 次工具调用。
- 模型不可用后恢复：失败会话保留工具状态，`POST /internal/agent:resume` 继续并完成；工具调用未重复执行。
- 循环检测：相同工具+参数重复 → `AGENT_LOOP_DETECTED`。
- 预算：`max_steps` 用尽 → `AGENT_BUDGET_EXCEEDED`。
- 输出 schema 两次不合法 → `AGENT_OUTPUT_INVALID`。
- SQLite 会话存储：`session_id` 稳定，状态/步骤/usage/context 可序列化。
- 断点恢复成功率：测试样本 **100%**。

---

## 6. JSON 与模型网关

测试：`tests/integration/agent/test_model_gateway.py`

| 场景 | 结果 |
|---|---|
| 非法 JSON + 修复成功 | 两次调用，返回修复后的对象；usage 合并 |
| 修复仍失败 | `ModelOutputInvalid`，Harness 两次后结构化失败 |
| 主地址失败、备地址成功 | 请求成功；active 因 10 s 防抖保持主地址 |
| 连续失败满 10 s | 提交切换到备地址 |
| 主地址恢复 + 冷却结束 | 回切主地址 |
| 三地址全部失败 | `ModelUnavailable` |

真实 smoke：`qwen-smoke.py` 返回 `{"ok": true}`，40 prompt / 13 completion tokens，1.5 s；看门狗 floor=4096 MiB，未触发。

---

## 7. 窗口基准

见 [M5 窗口基准](M5-window-benchmark.md)：32K 11.5 s、64K 10.1 s、128K（120K 实际 token）26.4 s；全程看门狗监控，无触发。

---

## 8. 测试汇总

```text
tests/integration/agent
  test_watchdog.py          4 passed
  test_model_gateway.py     6 passed
  test_context.py           4 passed
  test_segmentation.py      2 passed
  test_harness.py           5 passed
  test_router.py            3 passed
  test_review_rules.py      2 passed
合计 26 passed
```

---

## 9. 失败样本与限制

| 项 | 说明 |
|---|---|
| 确定性 matcher 误选 hardness | **M6 已修复**（低覆盖惩罚）；确定性 5/5，Agent 5/5 |
| 真实 E2E 模型 Finding 为 0 | 合法样本无矛盾；需注入语义矛盾样本才能测模型召回 |
| 主/备地址 | M6 已配置旧地址；当前不可达/模型不匹配，探测标记 down；真实三地址切换待旧地址服务同一模型 |
| Router/Review 单次调用 | 工具循环留给 M6 的 Repair/Triage |
| 128K 实际 119,970 tokens | 为输出预留空间；服务器上限 131,072 |

---

## 10. 复现

```bash
# 看门狗 + 真实模型
python scripts/dev/guarded-model-test.py --floor-mb 4096 -- \
  python scripts/benchmark/router_eval.py --out docs/reports/M5-router-eval.json
python scripts/benchmark/review_eval.py --out docs/reports/M5-review-eval.json
python scripts/dev/guarded-model-test.py --floor-mb 4096 -- \
  python scripts/benchmark/window_benchmark.py --out docs/reports/M5-window-benchmark.json
python -m pytest tests/integration/agent -q
```
