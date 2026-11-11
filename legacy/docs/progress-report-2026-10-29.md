# 项目进度汇报（截至 2026-10-29，2026-10-30 更新）

> 汇报范围：M0–M5 全部里程碑与收口项
> 数据时点：2026-10-29 23:30（Asia/Shanghai）；更新：2026-10-30
> **更新摘要（2026-10-30）**：G2.5 已通过（52 份语料 / 50 有效；hit 0.9000、novelty/T3 0.0267；抽取级影子 111 表 1.0）；G4 的 52 份 silent 审计、字段单元格深链与浏览器走查已通过，仅剩复核耗时/修正正确率；G3 压缩回归改为抽取字段级（0pp）。G2 与 G1.9 的未满足条款、G5 外部阻塞不变。详见 `docs/milestone-audit.md` 与 `docs/engineering.md` 10.47。
> 总体结论：**G2.5、G3 通过；G2、G4、G5 未通过；G1.9 未通过（成员/工作空间与容器化）**。

## 1. 里程碑总览

| 里程碑 | 门禁 | 状态 | 关键证据 | 主要缺口 |
|---|---|---|---|---|
| M0 立项/基线 | - | 完成 | 计划 v3 | - |
| M1 单文档 MVP | G1 | 通过 | Record F1 0.8733、Evidence 1.0、p95 193s | - |
| M1.5–M1.7 | - | 通过 | 引用图谱、困难表、覆盖审计 | - |
| M1.8 业务主数据 | G1.8 | 部分 | 已知词 1.0/1.0/1.0 | 真实词典端点不可用（E6） |
| M1.9 前后端 | G1.9 | 未通过 | E2E 主链路+字段复核通过；引擎 380/平台 19/Web 5 | 成员/工作空间管理（A12）、三平面容器化、1.35 仅模型核查 |
| M2 数据与微调 | G2 | **未通过** | field 0.7555、header 73 处错误 | 距 95%/98% 目标差距大（D1），需模型/数据投入 |
| M2.5 配方与冷启动 | G2.5 | **通过（2026-10-30）** | 52 份/50 有效：hit 0.9000、novelty/T3 0.0267；抽取级影子 111 表 1.0、核心回归 0 | - |
| M3 Agent 编排 | G3 | **通过** | 真实 Qwen 8 文档 STP **0.875**（7 published/1 human），mock 0.875，修复注入 3/3；压缩字段损失 0pp | 仅 `gbt14992` 保守人工（可接受） |
| M4 人机协同 | G4 | **未通过** | silent 0/52、字段深链+E2E 走查、高风险闸门/RBAC 可用 | 复核耗时基线、修正正确率（需真实人工事件） |
| M5 生产化 | G5 | **未通过** | 5 族 operational、证据率 1.0、silent 0、p95 175.1s、加密备份演练 PASS、扫描 0 findings | E1–E5、真实集群演练、成本/页达标 |

## 2. 近期已完成（本轮收口）

| 项 | 结果 |
|---|---|
| G3 达成 | 修复表型优先级、rowspan 跨行泄漏、Qwen 属性重复绑定、`N/mm²` 单位；真实 Qwen STP 0.375→0.75→**0.875** |
| 表型判定 | 力学表（含试样状态）、检验项目表（含化学成分行）、电导率表（含力学性能引用）均正确归类；G5 五族恢复 operational |
| C4 队列隔离 | `JobState.lane` + worker `--pool`/`WORKER_POOL`，API/批量支持 lane，compose/K8s 池值统一为 production |
| C7 反馈抽检 | `tools/feedback_sample.py` 哈希抽样 + `annotations.jsonl` 标注接口 + accuracy 指标（待真实事件） |
| C8 token 记账 | 客户端 `usage` → `trace.model_usage` → 编排 cost → `JobState.summary` / `metrics.json` → `cost_report` |
| C9 备份加密 | openssl AES-256-CBC（PBKDF2 100k）+ 密文校验 + 解密恢复；本地 Fernet 演练 PASS（含篡改检测） |
| C10 OpenAPI | 补 4 条字段复核端点与 6 个 schema，重新导出 62 paths |
| 模型平面 | IP 切至 `192.168.1.35`，按脚本重启 9989；配置/网络策略/文档同步 |

## 3. 未达标项明细

### 3.1 G2 数据与微调（未通过）

| 指标 | 目标 | 当前 | 差距 |
|---|---|---|---|
| field F1 | ≥95% | 0.7555 | 差约 19.4pp |
| 表头映射错误 | 0 | 73 处 | 需难例/数据扩增 |

- 现有手段（`vote` 双路映射、`sft_m2`）无增益也无回归，默认仍为 native；
- 根因是数据与模型能力，而非工程链路。

### 3.2 G2.5 配方与冷启动（通过，2026-10-30）

| 指标 | 当前 |
|---|---|
| 语料 | **52 份（50 份有效）** |
| active 配方 | 7 个 |
| 表型 unknown | 12（admin 130 张不计入） |
| 绑定率 | **0.9721**（450 张有效表） |
| novelty / T3 | **0.0267 / 0.0267** |
| 路由 | production 150 / explore 255 / human 45；文档级 production **0.9000** |
| 冷启动分层 | T1 150 / T2 288 / T3 12 |

- 已满足：25+ 份样本；抽取级影子 111 表、field_agreement 1.0、核心字段回归 0。

### 3.3 G4 人机协同（未通过）

| 项 | 状态 | 说明 |
|---|---|---|
| silent error | **0/52 份** | 目标 50 份已达成（D2 关闭） |
| 复核耗时 / Human Minutes | 未测 | 无真实复核事件（D3） |
| 一次通过率 | 代理值 1.0 | 无 edit/reject 事件，代理值不代表真实 |
| 修正正确率 | 未测 | 工具与标注接口已就绪（C7），待真实事件与领域标注 |
| 风险分级 | high 0 / medium 1704 / low 4729 | 已校准：medium 仅关键力学属性与缺单位（D4 关闭） |
| 证据深链 | 完成 | 字段行「定位」→ viewer 单元格高亮（bbox/引用/表格块回退） |
| 浏览器走查 | 已通过 | `e2e/test_main_flow.py`：复核→定位→返回→接受→退出 |

### 3.4 G5 生产化（未通过）

| 项 | 当前 | 目标/缺口 |
|---|---|---|
| 五族可运行 | chemical 0.9688 / mechanical 0.9720 / inspection 0.9617 / dimension 1.0 / classification 0.9778 | 5/5 operational |
| 证据率 | 1.0 | ≥95% ✅ |
| silent error | 0 | 0 ✅ |
| 单文档 p95 | 175.1s | ≤300s ✅ |
| 并发压测（mock） | p95 14.3s、失败 0、0.31 docs/s | 失败率 <2% ✅ |
| 成本 | 372 页 / 20 次抽取 / 1618 CPU 秒 / 中位 4.3s/页；金额 0 | 单价缺失（E4），成本/页未达标 |
| 备份 | 本地加密演练 PASS | Postgres/K8s 未演练（E2） |
| 安全 | 扫描 0 findings | 外部评审未排期（E3） |
| SLA | `insufficient_data`（14 jobs） | 生产/试点流量缺失（E1） |
| 试点/值班 | 模板与签字栏就绪 | 部门、名单、签字缺失（E5） |
| 真实集群 | 未部署/未做滚动升级演练 | 仅有 K8s/compose 交付物 |

## 4. 数据与模型缺口

| ID | 缺什么 | 数量/现状 | 影响 |
|---|---|---|---|
| D1 | 表头映射难例与训练数据 | 73 处错误；field 0.7555 | G2 不达标 |
| D2 | 审计语料 | 20/50 份 | G4 silent 覆盖不足 |
| D3 | 真实复核事件 | 0 条 | 复核耗时、一次通过率、修正正确率不可测 |
| D4 | 风险规则校准 | high 0、medium 5991 | 复核优先级失真，人工负担高 |

## 5. 代码遗留（非外部依赖）

| 项 | 现状 | 计划 |
|---|---|---|
| C5 定向检索/重 OCR | 覆盖缺失直接进人工 | 需设计“缺失字段→定位条款/重抽”路径 |
| M3 压缩抽取级回归 | 证据/表头无损，抽取器未消费上下文 | 接入上下文后再测 ≤1pp |
| C9 KMS 对接 | 加密已实现，口令经环境变量/文件 | 接 ExternalSecret/KMS + 轮换演练 |
| 旧 run token | 新任务已记账，旧 run 为 0 | 不回填，仅新任务统计 |
| 字段单元格深链 | 证据可定位到页 | 前端深链到单元格坐标 |

## 6. 外部输入状态（E1–E6）

| ID | 阻塞 | 责任方 | 已准备 | 需要提供 | 关闭标准 |
|---|---|---|---|---|---|
| E1 | 无生产流量，SLA 99.5% 不可测 | 试点部门 | `tools/sla_probe.py` → `eval/sla.json` | ≥200 完成任务；SLA 条款（窗口/口径/赔付） | `sla_probe` status=pass 且条款签字 |
| E2 | Postgres/K8s 恢复未演练 | 运维/基础设施 | 加密备份/恢复脚本、`postgres_drill.sh`、本地加密演练 PASS | 试点 K8s/Postgres 环境、备份介质、隔离命名空间 | `postgres_drill.sh` 行数一致 + `restore.sh` 整环境演练 PASS |
| E3 | 外部安全评审未排期 | 安全 | `docs/security-review-package.md`、扫描 0 findings | 评审方、排期、渗透测试 | 无高危 + 评审签字 |
| E4 | 成本单价未确认 | 业务 | `infra/cost_model.json` 四字段与 `pending_fields` | OCR/抽取/CPU/token 单价 | 金额可计算且成本/页达标 |
| E5 | 试点验收/值班名单未定 | 项目负责人 | `docs/pilot-acceptance.md` 签字栏、`docs/oncall.md` 排班模板 | 试点部门、值班名单、签字 | 四人签字 + 值班表生效 |
| E6 | 业务词典真实端点不可用 | 业务系统 | 已知词回退（已知项 1.0/1.0/1.0） | 真实端点与鉴权 | 联调通过 |

## 7. 优先级建议

1. **P0（决定 G2/G5 能否转正）**：D1 表头难例/数据扩增；E1 试点流量与 SLA 条款；E2 Postgres/K8s 演练。
2. **P1**：D2 补 30 份语料；D3 采集真实复核事件；E3 安全评审排期；E4 单价；E5 名单与签字。
3. **P2**：D4 风险规则校准；C5 定向检索；C9 KMS；单元格深链与浏览器走查。

## 8. 验证与证据索引

| 类别 | 结果/路径 |
|---|---|
| 测试 | 引擎 **376**、平台 **19**、web **5**；web `tsc --noEmit` 通过 |
| G3 | `metal-doc-agent/eval/m3-qwen-8docs.json` / `.md` |
| G4 | `metal-doc-agent/eval/m4.json` / `.md`、`eval/feedback.json` |
| G5 | `metal-doc-agent/eval/m5.json`、`eval/loadtest.json`、`eval/m5-cost.json` |
| 备份 | `metal-doc-agent/eval/backup-drill.json` / `.md`（加密 + 篡改检测） |
| 安全 | `metal-doc-agent/eval/security-scan.json`、`docs/security-review-package.md` |
| SLA | `metal-doc-agent/eval/sla.json`（当前 insufficient_data） |
| 验收包 | `metal-doc-agent/eval/pilot-pack.json` / `.md`（G5=false，6 项阻塞） |
| 审计总表 | `docs/milestone-audit.md`、`docs/engineering.md` 10.40–10.46 |

## 9. 结论

- 工程链路与 G3 已收口：解析→路由→抽取→校验→发布/人工全链路可运行，真实 Qwen STP 0.875；
- G2/G4/G5 的剩余项主要不是代码问题：G2 缺数据/模型能力，G4 缺真实事件与语料，G5 缺试点环境与外部签字；
- 在上述外部输入到位、且 C5 定向检索补齐后，可进入 G2/G4/G5 的复评。
