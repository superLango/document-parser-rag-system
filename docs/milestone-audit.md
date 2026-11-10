# 里程碑收口审计（2026-10-30）

> 依据：`development-plan-v3.md` + `stages/00–08` 的验收条件与当前代码/评测产物。
> 结论：**G2.5、G3 通过；G2、G4、G5 未通过；G1.9 未通过**。未通过项均非“基本完成”，而是有明确未满足条款：G1.9（成员/工作空间管理与容器化部署）、G2（模型字段/表头指标）、G4（复核耗时与修正正确率，需真实人工事件）、G5（外部输入）。以下按“代码可修 / 数据与模型 / 外部阻塞”分类。

## 1. 里程碑状态总览

| 里程碑 | 门禁 | 状态 | 关键证据 | 未满足项 |
|---|---|---|---|---|
| M0 立项/基线 | - | 通过 | 计划 v3 | - |
| M1 单文档 MVP | G1 | 通过 | Record F1 0.8733 / Evidence 1.0 / p95 193s | - |
| M1.5–M1.7 | - | 通过 | 引用图谱、困难表、覆盖审计 | - |
| M1.8 业务主数据 | G1.8 | 未通过 | 已知词 1.0/1.0/1.0 | E6 真实业务端点不可用 |
| M1.9 前后端 | G1.9 | **未通过** | E2E 主链路+字段复核通过；引擎 380/平台 19/Web 5 | 成员管理/工作空间未实现（A12）；三平面容器化未拉起；1.35 仅模型未现场核查 |
| M2 数据与微调 | G2 | **未通过** | field 0.7555 / header 73 / record 0.80 | 核心字段 ≥95%、表头 ≥98% 未达；G2 评审未签字 |
| M2.5 配方与冷启动 | G2.5 | **通过** | 52 份/50 有效：hit 0.9000、novelty/T3 0.0267；抽取级影子 111 表 1.0、核心回归 0 | - |
| M3 Agent 编排 | G3 | **通过** | 真实 Qwen STP 0.875；修复 3/3；压缩字段损失 0pp；p95 169.5s | - |
| M4 人机协同 | G4 | **未通过** | silent 0/52；E2E 字段复核→定位→接受；字段行深链 | 复核耗时 ↓≥50%、修正正确率需真实人工事件 |
| M5 生产化 | G5 | **未通过** | 5 族、证据率 1.0、silent 0、p95 175s、压测 14.3s、本地加密备份 PASS | SLA、Postgres/K8s 演练、外部安全评审、单价、试点签字/值班 |

## 2. 代码侧问题（本仓库已修复）

| ID | 问题 | 影响 | 结果 |
|---|---|---|---|
| C1 | `/metrics` 重复输出 HELP/TYPE | Prometheus 格式 | ✅ 按族输出一次 |
| C2 | 告警引用缺失直方图 | p95 告警无数据 | ✅ job `metrics.json` + `engine_pipeline_seconds` 直方图 |
| C3 | 复核风险行缺证据指针 | 无法定位原文 | ✅ `FieldRisk` 带 evidence/page + UI「定位」深链到 viewer 单元格 |
| C4 | worker 共享 FIFO，生产被探索挤占 | 队列隔离 | ✅ `JobState.lane` + `worker --pool` + API/batch lane |
| C5 | 覆盖缺失直接进人工 | STP 低 | ✅ `not_applicable` 语义 + 页预算/歧义规则（C5b） |
| C6 | classification/unknown 无配方 | novelty/T3 33.85% | ✅ 表型识别 + classification_v1；20 语料下 0 |
| C7 | 反馈集无抽检 | 修正正确率未测 | ✅ `tools/feedback_sample.py` 抽样/标注/指标；真实事件仍缺（D3） |
| C8 | token 未逐任务记账 | 成本不可核算 | ✅ usage → trace → summary → metrics → cost_report |
| C9 | 备份未加密 | 恢复演练不完整 | ✅ AES-256-CBC + objects.tgz + checksum + 篡改检测；本地演练 PASS |
| C10 | OpenAPI 缺字段复核端点 | 契约不同步 | ✅ 草案 + `packages/contracts/openapi.json`（62 paths） |
| C11 | 封面/审签/清单表被当成 T3 长尾 | T3 17.59% 假高 | ✅ 新增 `admin` 表型（不计入 novelty/T3）；unknown 102→12 |
| C12 | 影子只到绑定级 | G2.5 抽取级未测 | ✅ `evaluate_field_shadow` 逐字段重放，111 表 1.0、核心回归 0 |
| C13 | 风险几乎全 medium；单位紧贴表头漏识别 | 复核队列噪声 / 静默错误 | ✅ medium 仅关键力学属性（1704）；单位兜底；52 份 silent 0 |

## 3. 数据/模型问题

| ID | 问题 | 影响 | 状态 |
|---|---|---|---|
| D1 | native 表头映射 73 条错误 | G2 field 0.7555 < 0.95、header 0.781 < 0.98 | **未解决**（需扩 SFT 难例/改 prompt 或换抽取策略） |
| D2 | 50 份 silent 审计语料不足 | G4 审计覆盖 | ✅ 已扩至 52 份，0 错误 |
| D3 | 无真实复核事件 | 复核耗时/修正正确率不可测 | **未解决**（试点上线采集） |
| D4 | 风险优先级全 medium | 复核队列噪声 | ✅ 校准：high 0（无完整性异常）、medium 1704（关键力学）、low 4729 |

## 4. 外部阻塞（非代码可解）

| ID | 阻塞 | 影响 | 责任 |
|---|---|---|---|
| E1 | 无生产流量，SLA 99.5% 不可测 | G5 | 试点部门（`tools/sla_probe.py` 就绪） |
| E2 | Postgres/K8s 备份恢复未演练 | G5 | 运维（`postgres_drill.sh` + `restore.sh` 就绪） |
| E3 | 外部安全评审未排期 | G5 | 安全（`docs/security-review-package.md` 就绪） |
| E4 | 成本单价未确认 | G5 | 业务（`infra/cost_model.json` pending_fields） |
| E5 | 试点验收/值班名单未定 | G5 | 项目负责人（模板就绪） |
| E6 | 业务词典真实端点不可用 | M1.8 | 业务系统 |
| E7 | A12 多租户/成员管理决策未定 | G1.9 | 架构/业务 |
| E8 | 三平面容器化部署环境 | G1.9 | 基础设施 |
| E9 | 1.35 仅模型的主机核查 | G1.9 | 现场运维 |

## 5. 本轮执行（2026-10-30）

1. **语料扩容**：从 `markdown/` 去重选取 32 份，与 20 份基线合并为 52 份（50 份有效）。
2. **表型收口**：新增 `admin` 表型；补充检验/工艺/夹杂物/疲劳/组分/标准号标记；T3 17.59% → 2.67%。
3. **抽取级影子**：`evaluate_field_shadow` + `tools/shadow_run.py` 双报告；候选机械配方 111 表 field 1.0、核心回归 0。
4. **静默错误归零**：紧贴表头单位解析 + 标准属性默认单位；52 份 silent 0。
5. **风险校准**：medium 仅关键力学属性与缺单位；文档风险 medium 26 / low 26。
6. **G4 走查**：扩展 `e2e/test_main_flow.py`（字段复核 → 定位 → 返回 → 接受 → 退出），真实 Chromium 通过；`run_main_flow.ps1` 落盘测试日志。
7. **G3 压缩回归**：`context_regression` 增加抽取字段集合与 `field_loss_rate`，压缩后 `lost_fields=[]`。
8. **测试**：引擎 380、平台 19、Web typecheck + 5 通过。

## 6. 验收口径

- 代码侧：每项有测试/产物，回归全绿（引擎 380、平台 19、web 5 + E2E）。
- 指标侧：`eval/coldstart-52.*`、`eval/recipes/routing-52.json`、`eval/recipes/shadow-*.json`、`eval/m4-52.*`、`eval/m5.*`、`eval/loadtest.md`。
- 未满足条款保持未通过，不以“基本/条件达成”表述；外部输入到位后按对应附录复评。
