# 项目差距清单报告（现状 vs 重构方案 vs 里程碑计划）

> 生成时间：2026-11-13
> 2026-11-14 更新：30 份人工金标已接入 `gold-registry.json` / `gold-eval.json`，GAP-01 关闭；新增 gold F1 基线（0.3618）与表格指标。
> 对比基线：[项目全维度核查报告](project-full-audit-2026-11-12.md)、[架构重构方案](../architecture-refactor-plan.md)、[整体开发计划](../development-plan.md) 与 M0–M8 里程碑文档
> 运行证据：[full-audit50.md](full-audit50.md)（2026-11-13）、[scale-gate.md](scale-gate.md)（2026-11-12）、[gold-standards.json](gold-standards.json)、[M8-loadtest.md](M8-loadtest.md)、[decision-log.md](../decision-log.md)
> 说明：本报告只列尚未闭环或验收未达标的项；已闭环项在里程碑总表中标注，不再重复展开。

## 1. 结论摘要

- **架构承诺**：七服务、契约驱动、配方不可变、run 冻结版本、反馈修复闭环、L3 审批、可观测均已落地；审计中的 6 组 P0 已全部闭环或转“受限通过”。
- **里程碑**：M0 受限完成；M1/M3/M4/M6/M7 功能闭环；M2/M5/M8 仍有验收缺口。
- **仍未完成的关键项集中在四类**：
  1. **指标与数据质量**：50 份结构化 40/50；牌号/值原文命中约 70%；重复键记录 368 条；F1 0.6025、静默 2.62%，未达 Phase 2/3 门槛。
  2. **验收证据**：金标仅 2 份（目标 ≥30）；扫描件成功率未统计；M8 灰度 10%/50%/100% 未真实执行；并发 4 × 三窗口未压测。
  3. **工程收尾**：Run.progress 字段、M0 的 K8s 正式部署/ADR/uv.lock、V-007 生产 K8s 资源配置回填。
  4. **产品能力（W1–W6）**：W2 Tier 1/2、W3 列级继承、W4 金标/TEDS/CI 门禁、W5 异步与多引擎、W6 灰度自动回滚。

## 2. 里程碑差距总表

| 里程碑 | 审计状态 | 当前判断 | 剩余差距 | 证据 |
|---|---|---|---|---|
| M0 骨架 | 基本完成 90% | 已完成（受限） | K8s 七服务正式部署、ADR、`uv.lock` 未完成 | [M0-project-scaffold.md](../M0-project-scaffold.md#L9)、`new_app` 下无 `uv.lock` |
| M1 编排主链路 | 基本完成 85% | 已完成 | `Run.progress` 字段仍未加（P2） | AUD-A04；orchestration 代码无 `progress` 字段 |
| M2 OCR/表格 | 基本完成 90% | 基本完成 | 扫描件成功率未系统统计；profile 命名与文档不一致；无框线表依赖 layout + GLM | AUD-C04、AUD-D04；[M8-loadtest.md](M8-loadtest.md) |
| M3 配方注册 | 基本完成 90% | 已完成 | 无（持久化已修复） | 审计 5.1 第 3 项；compose/K8s 已挂载数据目录 |
| M4 沙箱 | 基本完成 90% | 已完成（Kata 未实测） | Kata 未实测；运行时决策已回填 | 审计 5.2 第 16 项；decision-log |
| M5 Agent | 部分完成 75% | 基本完成 | RouterAgent 默认关闭；并发 4 × 三窗口组合压测未做 | [M5-agent-runtime.md](../M5-agent-runtime.md#L348)；[M8-loadtest.md](M8-loadtest.md) 仅 run 并发 3 |
| M6 反馈闭环 | 部分完成 80% | 已完成 | 无（审批语义与 shadow 出口已按 D-015 闭环） | 审计第 154–156 行 |
| M7 前端 | 部分完成 80% | 已完成 | 无（SSE、证据定位、搜索分页、词典导入 UI 已补） | 审计 5.3 第 17 项 |
| M8 词典/切换 | 受限通过 85% | 受限通过 | F1/静默未达 Phase 3；灰度未真实执行；V-007 待回填 | [M8.md](../acceptance/M8.md#L32)、[decision-log.md](../decision-log.md#L744) |

## 3. 未完成项清单（按优先级）

### 3.1 P1：本阶段应完成

| ID | 来源 | 差距 | 当前证据 | 关闭条件 |
|---|---|---|---|---|
| GAP-01 | AUD-A11 / AUD-D04 / 审计 5.2 第 15 项 | 金标 ≥30 份未达成 | **已关闭（2026-11-14）**：[gold-registry.json](gold-registry.json) 30 份、25,377 items；[gold-eval.md](gold-eval.md) 已产出基线 | 金标质量门禁已可启用（Phase 3 阈值 F1≥0.80 尚未达到） |
| GAP-02 | full-audit50 | 50 份标准结构化仅 40/50，10 份为 `REVIEW_FAILED`/`FAILED` 且 0 记录 | [full-audit50.md](full-audit50.md#L10)、[明细 L51–L90](full-audit50.md#L51-L90) | Phase 2 ≥45/50；Phase 3 ≥48/50 |
| GAP-03 | full-audit50 | 牌号/值原文命中率仅 70.03% / 70.78% | [full-audit50.md](full-audit50.md#L18-L19) | ≥99% / ≥99% |
| GAP-04 | full-audit50 / W3 | 重复键记录 368、同键多条件 261 | [full-audit50.md](full-audit50.md#L23-L24) | 文档内重复键 ≤5 组 |
| GAP-05 | 审计 5.2 第 15 项 / M8 验收 | Phase 3 指标未达：legacy F1 0.6025、静默 2.62%；gold F1 0.3618、静默 24.04% | [scale-gate.md](scale-gate.md#L8-L9)；[gold-eval.md](gold-eval.md#L1-L29)；[M8.md](../acceptance/M8.md#L30-L31) | legacy F1 ≥0.80、静默 ≤2%；gold F1 ≥0.80、静默 ≤2% |
| GAP-06 | AUD-C04 / Phase 3 | 扫描件成功率未统计 | [M8-loadtest.md](M8-loadtest.md#L21-L23) 仅说明并发场景；`--scan-fixture` 无样本 | 扫描件成功率 ≥90% 并纳入门禁 |
| GAP-07 | AUD-A10 / M8 验收 | 灰度 10%→50%→100% 未真实执行 | [M8.md](../acceptance/M8.md#L32)、[M8.md](../acceptance/M8.md#L50) | 生产按 10%/50%/100% 执行并保留回滚记录 |

### 3.2 P2：工程收尾与后续优化

| ID | 来源 | 差距 | 当前证据 | 关闭条件 |
|---|---|---|---|---|
| GAP-08 | AUD-A04 | Run 无 `progress` 字段，前端只能显示阶段 | orchestration 代码无 `progress` 字段 | 增加字段、API 输出与前端展示 |
| GAP-09 | M5 验收 | 并发 4 × 32K/64K/128K 三窗口组合压测未做 | [M5-agent-runtime.md](../M5-agent-runtime.md#L348)明确留待 M8；[M8-loadtest.md](M8-loadtest.md) 未覆盖 | 产出组合压测报告并回填 D-005 |
| GAP-10 | M0 验收 | K8s 七服务正式部署、ADR、`uv.lock` 未完成 | [M0-project-scaffold.md](../M0-project-scaffold.md#L9)；`new_app` 下无 `uv.lock` | K8s 部署验证通过，ADR 与锁文件入库 |
| GAP-11 | AUD-C06 / V-007 | 生产 K8s 资源配置待回填 | [decision-log.md](../decision-log.md#L744) | 切换窗口确定节点池、副本、HPA、存储后回填 |
| GAP-12 | AUD-A05 | RouterAgent 能力已接入但默认关闭 | `ROUTE_AGENT_ENABLED` 默认 false | 回归稳定后开启，或正式登记为“按需开启” |
| GAP-13 | AUD-D05 | 策略链行为对齐旧提取器，存在旧缺陷带入风险 | 审计 4.4；`strategy-coverage.md` 显示 `grade_property_tail`/`element_matrix` 0 命中 | 明确保留策略的边界与退出条件，列入观察项 |

## 4. 产品能力缺口（W1–W6）

> 来源：[implementation-plan-current-vs-target.md](implementation-plan-current-vs-target.md)。这一组是“表格/版面能力”的方案差距，与上面的里程碑验收缺口并行存在。

| 工作包 | 状态 | 已落地 | 未落地 |
|---|---|---|---|
| W1 版面服务化 | 基本完成（layout-first 替代） | 188.75:9978 `layout_api`；`LayoutFirstOcrAdapter` 全量 PDF 走版面；table 块裁剪送 GLM；compose/k8s/.env 已配 | `layout_native_fallback`/`layout_table_crop` 独立开关；`LAYOUT_API_TOKEN`；`/healthz` 返回权重 SHA |
| W2 表格三级策略 | 部分完成 | Tier 3 VLM 兜底生效，无框线表由版面 + GLM 处理 | `text_tables.py` 文本坐标聚类（Tier 1）；TATR/PP-Table/Docling 结构模型 PoC（Tier 2）；表格质量分 |
| W3 表头/条件/单位继承 | 部分完成 | 配方 1.6.1 的 `bindings.conditions` 已含壁厚/产品形式/交货/方向/温度等；`header_paths` 拼接父级 | `column_units`/`column_conditions`/`column_elements`；`_extract_unit` 使用列单位；`m8_effect_compare.py` 原始/归一化双口径 F1 |
| W4 金标与回归门禁 | 基本完成（2026-11-14） | 30 份金标注册、`gold_eval.py`（F1/静默/覆盖/单位/条件/表型/表头/单元格/TEDS）、`gate_scale.py --require-gold`、CI 契约检查 | 无文本层 PDF 先 GLM 再核对；50 份 + 金标全链路跑通（需服务环境） |
| W5 OCR 韧性与多引擎 | 基本未做 | 仅有超时、重试、layout 熔断、native 回退 | >20 页异步队列；PaddleOCR-VL/MinerU 第二引擎；OCR 健康检查与自动降级/回切 |
| W6 灰度与回滚 | 部分完成 | `recipe_channel`、shadow 批量比较、`shadow_auto_promote`、手动 promote/abandon/rollback | `TABLE_ENGINE` 开关；`LAYOUT_NATIVE_FALLBACK` 独立开关；10% 灰度自动对比与异常自动回滚 |

## 5. 指标现状与门槛

| 指标 | 当前 | Phase 1 | Phase 2 | Phase 3 | 结论 |
|---|---|---|---|---|---|
| 结构化成功 | 40/50 | ≥40/50 | ≥45/50 | ≥48/50 | Phase 1 达标，Phase 2/3 未达 |
| Field F1（60 份） | 0.6025 | ≥0.60 | ≥0.70 | ≥0.80 | Phase 1 达标，Phase 2/3 未达 |
| 静默错误率 | 2.62% | ≤3% | ≤2% | ≤2% | Phase 1 达标，Phase 2/3 未达 |
| 牌号原文命中 | 70.03% | ≥99% | ≥99% | ≥99% | 未达 |
| 字段值原文命中 | 70.78% | ≥99% | ≥99% | ≥99% | 未达 |
| 单位存在率 | 99.97% | 100% | 100% | 100% | 基本达标 |
| 文档内重复键 | 368 条记录 / 261 组同键多条件 | ≤5 组 | ≤5 组 | ≤5 组 | 未达 |
| 金标数量 | 30 份 | ≥30（Phase 3 前） | ≥30 | ≥30 | 达标 |
| gold Field F1 | 0.3618 | — | — | ≥0.80 | 未达 |
| gold 静默错误率 | 24.04% | — | — | ≤2% | 未达 |
| p95 延迟 | 11.25s | ≤15s | ≤15s | ≤15s | 达标 |
| 扫描件成功率 | 未统计 | 基线 | ≥80% | ≥90% | 未验收 |

## 6. 建议执行顺序

1. **数据质量收敛**：GAP-03/04 + W3 列级继承，先解决原文命中与重复键，这是当前对可用性影响最大的部分。
2. ~~**金标与门禁分级**：GAP-01 + W4~~（已完成 2026-11-14：30 份金标注册、gold 评测与门禁开关就绪；下一步用 gold 报告的缺口驱动修复）。
3. **失败文档收敛**：GAP-02，对 10 份 0 记录文档逐份归因（版面/表格/配方）。
4. **Phase 3 指标与灰度**：GAP-05/06/07 + W4/W5，补扫描件统计、真实灰度与自动回滚。
5. **工程收尾**：GAP-08/09/10/11，补 `Run.progress`、并发压测、K8s 正式验收与 V-007。
6. **方案能力补强**：W2 Tier 1/2、W6 `TABLE_ENGINE` 与独立开关。

## 7. 口径说明

- [full-audit50.md](full-audit50.md) 的“零记录文档 0”只统计结构化成功文档；明细中 10 份 `REVIEW_FAILED`/`FAILED` 实际为 0 记录，不能据此认为全部文档已有记录。
- F1 有两套口径：`legacy-regression F1`（发布门禁 ≥0.60）与 `gold F1`（Phase 3 ≥0.80）。本报告分别列示，不以一套口径替代另一套。
- 静默错误当前 2.62% 为 legacy 回归口径；Phase 3 目标 ≤2%。
- 里程碑完成度为审计评估值，不是验收结论；最终以第 3 节关闭条件为准。

## 8. 证据文件

- 全维度核查：[project-full-audit-2026-11-12.md](project-full-audit-2026-11-12.md)
- 最新 50 份审计：[full-audit50.md](full-audit50.md)
- 发布门禁：[scale-gate.md](scale-gate.md)、[gate_scale.py](../../scripts/benchmark/gate_scale.py)
- 金标：[gold-standards.json](gold-standards.json)、[gold-standards.md](gold-standards.md)
- 策略命中：[strategy-coverage.md](strategy-coverage.md)
- M8 验收：[M8.md](../acceptance/M8.md)
- M8 压测：[M8-loadtest.md](M8-loadtest.md)
- 决策记录：[decision-log.md](../decision-log.md)
- 方案对比：[implementation-plan-current-vs-target.md](implementation-plan-current-vs-target.md)
