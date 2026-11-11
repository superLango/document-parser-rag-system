# 金属材料检验标准 Agent 结构化抽取 · 开发计划

> 细化版：`development-plan-v2.md`（2026-10-26，按当前进度重新基线并拆到任务级）
> 依据：《金属材料检验标准 Agent 结构化抽取项目方案》v1.8（冷启动版）
> 版本：v1.0（历史版本，已被 `development-plan-v2.md` 取代）
> 状态：保留用于对照；执行以 v2.0 为准
> 原则：不承诺日历时间，以里程碑退出条件推进；没有评测基线，不进入下一阶段

---

## 0. 一页纸结论

**首个目标不是“全品类全自动”，而是打穿一条可审计的垂直切片：**

```text
PDF 上传
  → GLM-OCR 逐页识别
  → TableGrid 网格化
  → 表画像分类
  → Qwen3.5-9B 结构化抽取
  → 确定性归一化
  → L0–L2 校验
  → result.json + evidence.jsonl + audit.md
```

**首期三份打样文档**

| 文档 | 覆盖点 | 主要难点 |
|---|---|---|
| GB/T 1591-2018 | 化学成分、力学性能、复杂表头 | 5 行表头、C 按厚度拆子列 |
| GB/T 40303-2021 | 多块化学表、级别分组 | 3 个“级别”表头块、27 个元素 |
| Q-Du 302-2015 | 力学性能、方向/状态条件 | 条件来自表头分组 |

**关键路径**

```text
M0 契约与黄金集
  → M1 单文档垂直切片（3 份 → 20 份）
  → M1.5 引用图谱 + 困难表头
  → M1.7 全文档覆盖
  → M2 数据与微调
  → M2.5 配方注册表 + 冷启动
  → M3 Agent 编排
  → M4 人机协同
  → M5 生产化
```

**三条红线**

1. **没有证据的值不发布**：每个数值必须能回到页/表/行/列/quote。
2. **不可复现的路径不进生产**：生产只跑已注册配方和确定性 Workflow。
3. **不能证明覆盖就不算完成**：必填字段必须有证据或明确的 missing / ambiguous / not_applicable。

**第一轮迭代交付**

- 3 份文档端到端跑通；
- `result.json` + `evidence.jsonl` + `audit.md`；
- 一份错误分布报告；
- 一个可重复的 `run_doc` CLI；
- 一个 3 份文档的迷你黄金集与评测脚本。

---

## 1. 范围与不做

### 1.1 首期范围（In Scope）

- PDF 上传、任务管理、断点续跑；
- GLM-OCR 本地部署与页级 Markdown/HTML 输出；
- TableGrid：rowspan/colspan、表头树、单位、脚注、跨页合并；
- 文档画像：`document_type`、`outline_mode`、`table_profile`、`table_orientation`、`table_link_mode`、`coverage_template`；
- 引用图谱：规范性引用 + 行内引用、注日期/不注日期、1 跳 schema 相关展开；
- 抽取：化学成分、力学性能、热处理、尺寸偏差、检验规则、取样/试验方法；
- 校验：L0 Schema、L1 证据、L2 领域规则、L3 交叉一致性、L3.5 覆盖审计、L4 LLM Judge（仅可疑字段）；
- 证据链与审计包；
- 配方注册表、Router、三条队列、L0–L5 晋升；
- LangGraph 状态机、预算、修复循环、人工中断；
- 复核工作台（M4）；
- 批量 API 与本地化部署（M5）。

### 1.2 首期不做（Out of Scope）

- “所有规范性条款/所有表格”的全量结构化；首期以 schema 必填字段为准；
- 任意自定义 schema 的自由生成；首期只支持注册过的 profile；
- 多租户 SaaS、计费、复杂权限体系（M5 再补 RBAC/配额）；
- 实时协作、移动端；
- 生产环境执行模型生成的任意代码；
- 未经影子验证的自动发布；
- 全量引用闭包；首期只做 1 跳、与 schema 相关的规范性引用。

### 1.3 Schema 优先级

| 优先级 | 模块 | 字段示例 |
|---|---|---|
| P0 | 文档元数据 | 标准号、版本、名称、发布/实施日期、替代关系 |
| P0 | 牌号/级别 | grade、grade_level、condition |
| P0 | 化学成分 | 元素、下限/上限/范围、单位、脚注 |
| P0 | 力学性能 | Rm、Rp0.2、A、Z、KV2、硬度、温度、方向、试样状态 |
| P1 | 热处理 | 固溶、时效、退火、淬火+回火参数 |
| P1 | 尺寸/偏差 | 厚度/直径范围、偏差类型、单位 |
| P1 | 检验规则 | 检验项目、取样数量、取样位置、试验方法、判定 |
| P1 | 引用 | 引用标准、条款/表、版本、解析依据 |
| P2 | 覆盖 | 字段→位置、状态、证据、缺口 |

---

## 2. 团队与职责

### 2.1 最小配置

| 角色 | 职责 | 投入方式 |
|---|---|---|
| 技术负责人/架构 | 契约、状态机、技术决策、验收 | 全程 |
| 文档 AI 工程师 | OCR、TableGrid、OutlineGraph、CoveragePlan、引用 | 全程 |
| 后端工程师 | API、队列、存储、任务、审计 | 全程 |
| ML/Infra 工程师 | GLM-OCR、Qwen、vLLM、GPU、模型版本 | M0–M2、M5 |
| 领域专家 | Schema、规则、黄金集、配方审批 | M0 起持续，按批次 |
| QA/评测工程师 | 黄金集、指标、回归、审计抽样 | M0 起持续 |
| 前端工程师 | 复核工作台、证据高亮 | M4 起 |

> 最少可压缩为 4 人：技术负责人 + 文档 AI + 后端/Infra + 领域专家；QA 由技术负责人兼，前端在 M4 外包/复用。

### 2.2 RACI（关键决策）

| 决策 | R | A | C | I |
|---|---|---|---|---|
| Schema v0 | 文档 AI | 技术负责人 | 领域专家 | 业务 |
| 黄金集与标注规范 | QA | 技术负责人 | 领域专家 | 业务 |
| 验收阈值 | QA | 业务负责人 | 技术负责人、领域专家 | 团队 |
| 模型版本/部署 | ML/Infra | 技术负责人 | 文档 AI | 团队 |
| 配方晋升 L4 | 文档 AI | 技术负责人 | 领域专家、QA | 业务 |
| 自动发布策略 | 后端 | 业务负责人 | 技术负责人、领域专家 | 团队 |
| 生产发布/回滚 | 后端/Infra | 技术负责人 | QA | 业务 |

---

## 3. 技术栈与仓库

### 3.1 技术栈

| 层 | 选型 | 说明 |
|---|---|---|
| API | FastAPI + Pydantic v2 | 契约优先，OpenAPI 自动生成 |
| 编排 | LangGraph 1.x | 显式状态、checkpoint、interrupt、time travel |
| 队列 | Redis + Dramatiq/Arq | 生产/探索/人工三条队列 |
| 数据库 | Postgres 16 | 任务、状态、事件、配方、审计 |
| 对象存储 | MinIO/S3 | 页面图、Markdown、TableGrid、证据 |
| OCR | GLM-OCR + vLLM | 页级输出；保留页码映射 |
| 抽取 | Qwen3.5-9B + vLLM guided JSON | 两阶段抽取；LoRA 可选 |
| 表格 | 自研 TableGrid | BeautifulSoup/lxml + 几何回退 |
| 评测 | pytest + 自研 eval runner | 字段级/记录级/覆盖/证据 |
| 可观测 | OpenTelemetry + Langfuse | trace、成本、阶段指标 |
| 部署 | Docker Compose（dev）/ K8s（prod） | GPU 池隔离 |

### 3.2 仓库结构

```text
metal-doc-agent/
├─ apps/
│  ├─ api/                 # FastAPI：jobs、result、evidence、review、recipes
│  └─ worker/              # 队列消费者：production / exploration / review
├─ packages/
│  ├─ ingest/              # PDF 解析、页图、manifest
│  ├─ ocr/                 # GLM-OCR adapter、mock OCR
│  ├─ tablegrid/           # HTML 表格 → TableGrid
│  ├─ outline/             # OutlineGraph、条款树
│  ├─ refs/                # 引用解析、版本表、ReferenceGraph
│  ├─ coverage/            # CoveragePlan、CoverageAudit
│  ├─ extract/             # Qwen 调用、prompt、guided JSON
│  ├─ validate/            # L0–L4、领域规则
│  ├─ recipes/             # 配方 schema、注册表、Router
│  ├─ schemas/             # Pydantic 契约
│  ├─ eval/                # 黄金集、指标、回归
│  └─ common/              # 日志、错误、ID、存储
├─ ui/                     # 复核工作台（M4）
├─ infra/
│  ├─ docker/              # Compose、Dockerfile
│  ├─ k8s/                 # 部署清单（M5）
│  └─ models/              # 模型版本、启动脚本
├─ tests/
│  ├─ unit/
│  ├─ contract/
│  ├─ integration/
│  └─ e2e/
└─ docs/
   ├─ architecture.md
   ├─ api.md
   ├─ schemas.md
   └─ runbook.md
```

### 3.3 环境

| 环境 | 用途 | 配置 |
|---|---|---|
| dev | 本地开发 | CPU + mock OCR/mock LLM；Docker Compose |
| staging | 集成/评测 | 1 张 GPU；真实 GLM-OCR + Qwen |
| prod | 生产 | GPU 池；API/worker 分离；监控/告警 |

### 3.4 核心契约（Pydantic v2，JSON Schema 导出）

```text
DocumentProfile
Page
TableGrid
OutlineGraph
CoveragePlan
ClauseRecord
ReferenceGraph
ExtractionPlan
Record
Evidence
AuditReport
```

契约规则：

- 所有 artifact 带 `schema_version`、`producer_version`、`created_at`；
- 大产物存对象存储，state 只放 URI/指针/摘要；
- 证据不可为空；缺失值用 `null + status`，不猜；
- 任何 schema 变更必须版本化，旧结果可回读。

---

## 4. 里程碑与退出条件

| 里程碑 | 目标 | 关键交付 | 退出条件 | 依赖 |
|---|---|---|---|---|
| M0 | 立项与基线 | Schema v0、20 份黄金集、人工/商用基线、环境 | Schema 签字；黄金集 v0；环境确认；基线报告完成 | — |
| M1 | 单文档 MVP | OCR、TableGrid、zero-shot 抽取、L0–L2、JSON/证据 | 20 份 Schema 100%；证据 ≥95%；简单表 ≥85%；扫描件 ≥75%；30 页 p95 ≤5 分钟 | M0 |
| M1.5 | 引用图谱 + 困难表 | 引用解析、版本策略、约束合并、表头重建 | 引用解析 ≥90%；关键引用 100%；GB/T 1591 3/3 行；依赖字段 +5pp；≤8 份/文档 | M1 |
| M1.7 | 全文档覆盖 | OutlineGraph、CoveragePlan、ClauseRecord、表-条款链接 | ≥4 种 profile；覆盖 ≥95%；条款 F1 ≥90%；链接 ≥95%；孤儿 <1% | M1.5 |
| M2 | 数据与微调 | 错误分类、教师蒸馏、LoRA、两阶段抽取、guided JSON | 留出集核心字段 ≥95%；幻觉 <1%；表头映射 ≥98%；无回归 | M1.7 |
| M2.5 | 配方注册表 | 配方 schema、Router、三队列、L0–L5、影子、回滚 | 命中 ≥80%；首批 25 份 ≥6 个 active；Novelty <20%；Backlog 有界；T3 <5% | M2 |
| M3 | Agent 编排 | LangGraph、修复循环、断点续跑、批量 API、上下文预算 | STP ≥80%；修复 ≥70%；无死循环；成本可核算；压缩回归 ≤1pp | M2.5 |
| M4 | 人机协同 | 复核工作台、审计报告、主动学习 | 复核时间下降 ≥50%；发布 100% 有证据；50 份审计 silent error=0 | M3 |
| M5 | 生产化 | K8s、RBAC、SLA、监控、灰度、备份、扩展 | 试点验收；安全评审；SLA 99.5%；成本/页达标；可回滚 | M4 |

### 顺序纪律

- M0 契约未签字前，不写业务代码；
- M1 之前不微调；
- M1.5 之前不做全量引用闭包；
- M1.7 之前不追求“全条款/全表格”覆盖；
- M2.5 之前不做生产级配方自动化；
- M3 之前不做全自动发布；
- M4 之前不做复杂复核 UI。

### 4.1 M0 · 立项与基线

| ID | 任务 | 交付 | 验收 |
|---|---|---|---|
| M0-01 | 确认首期标准族与 schema 边界 | 范围说明 | 业务/领域签字 |
| M0-02 | 定义 Schema v0 | `schemas.md` + Pydantic | 20 份文档可映射 |
| M0-03 | 选 20 份黄金集（8 数字原生 + 12 扫描） | `goldset/v0/manifest.json` | 覆盖 4 类文档、3 类表 |
| M0-04 | 制定标注规范 | `annotation.md` | 单元格级 + 条款级；双人一致性 |
| M0-05 | 人工抽取基线 | baseline report | 字段级 P/R/F1、错误分类 |
| M0-06 | 商用智能体基线（2 家） | baseline report | 同文档、同 schema、字段级 |
| M0-07 | 本地部署环境 | Compose + GPU 清单 | GLM-OCR/Qwen 可启动 |
| M0-08 | 仓库骨架 + CI | repo + pipeline | lint/type/unit 通过 |

### 4.2 M1 · 单文档 MVP

> 先用 3 份打样文档跑通垂直切片，再扩到 20 份黄金集；M1 退出条件按 20 份评。

| ID | 任务 | 交付 | 验收 |
|---|---|---|---|
| M1-01 | 上传 API + 任务表 | `POST /v1/jobs` | 幂等、可查询 |
| M1-02 | 对象存储与 artifact 命名 | `artifacts/{job}/...` | 可回读、版本化 |
| M1-03 | GLM-OCR adapter | `ocr.md` + `pages.json` | 页码映射、页图保留 |
| M1-04 | HTML 表格 → TableGrid | `tablegrid.json` | rowspan/colspan、表头树、单位、脚注 |
| M1-05 | 表画像分类 v0 | `TableProfile` | 3 类表 ≥90% |
| M1-06 | zero-shot 抽取 | `result.draft.json` | guided JSON、raw + value |
| M1-07 | 归一化 | normalizer | 数字空格、比较符、区间、单位、旧符号 |
| M1-08 | L0/L1/L2 校验 | `audit.md` | schema/证据/领域规则 |
| M1-09 | 证据写入 | `evidence.jsonl` | 每值可回读 |
| M1-10 | CLI `run_doc` | `docparse run` | 一条命令跑完 |
| M1-11 | 3 份迷你黄金集 | `goldset/mini` | 单元格级标注 |
| M1-12 | 评测脚本 | `eval/report.md` | 字段/记录/证据指标 |

### 4.3 M1.5 · 引用图谱 + 困难表

| ID | 任务 | 交付 | 验收 |
|---|---|---|---|
| M1.5-01 | 引用行解析 | `references.json` | 标准号 + 年号 + 名称 + 条款/表 |
| M1.5-02 | 注日期/不注日期策略 | `resolution_basis` | 记录版本依据 |
| M1.5-03 | 本地标准库/版本表 | `standards.db` | 可查现行版本 |
| M1.5-04 | 相关性分类 | `relevance` | 规范性/资料性/相关字段 |
| M1.5-05 | 1 跳展开 + 预算 | `reference_graph.json` | ≤8 份/文档、≤30 页 |
| M1.5-06 | 约束合并 | `constraints.json` | 被引用标准 → 约束 |
| M1.5-07 | GB/T 1591 表 1 表头重建 | `tablegrid` patch | 3/3 行完成映射 |
| M1.5-08 | 引用缺口报告 | `reference_gaps.json` | 缺失/冲突/未入库 |

### 4.4 M1.7 · 全文档覆盖

| ID | 任务 | 交付 | 验收 |
|---|---|---|---|
| M1.7-01 | OutlineGraph | `outline.json` | 章/条/表/图 + 页码 |
| M1.7-02 | CoveragePlan | `coverage_plan.json` | required/optional/na + 证据 |
| M1.7-03 | ClauseRecord | `clause/{id}.json` | 条款号、参数、证据 |
| M1.7-04 | 表-条款链接 | `links.json` | 显式 → caption → 最近条款 |
| M1.7-05 | 覆盖审计 L3.5 | `coverage_audit.json` | 缺失/歧义/孤儿行 |
| M1.7-06 | 定向检索/重 OCR | `retrieval.log` | 缺口可回退 |
| M1.7-07 | 文档画像 + 模板 | `document_profile` | 6 类模板注册 |
| M1.7-08 | 转置表/版本校验 | orientation/version check | JX-25-035、GBT 14992 通过 |

### 4.5 M2 · 数据与微调

| ID | 任务 | 交付 | 验收 |
|---|---|---|---|
| M2-01 | 错误分类体系 | `error_taxonomy.md` | 解析/表头/归一化/语义/引用/覆盖 |
| M2-02 | 训练数据构建 | `train.jsonl` | 单元格级 + 条款级 + 扰动 |
| M2-03 | 教师蒸馏 | teacher outputs | 与黄金集对齐 |
| M2-04 | LoRA 训练 | adapter | held-out 无泄漏 |
| M2-05 | guided JSON | schema + decoder | 非法 JSON=0 |
| M2-06 | 两阶段抽取 | header→row | 长表稳定 |
| M2-07 | held-out 评测 | `eval/m2.md` | 核心 ≥95%；幻觉 <1% |
| M2-08 | 回归 | regression report | 相较 M1 无回归 |

### 4.6 M2.5 · 配方注册表 + 冷启动

| ID | 任务 | 交付 | 验收 |
|---|---|---|---|
| M2.5-01 | 配方 schema | `recipe.schema.json` | 声明式、可版本化 |
| M2.5-02 | 结构签名与检索 | `signature` | top-k + 置信度 |
| M2.5-03 | 参数绑定 | `bindings` | 子列/表头别名/块结构 |
| M2.5-04 | Router | `route_decision` | production/explore/human |
| M2.5-05 | 三条队列 | queues | 互不阻塞 |
| M2.5-06 | L0–L5 晋升 | registry | L2/L3/L4 闸门 |
| M2.5-07 | 影子运行 | shadow report | 同族一致 ≥98% |
| M2.5-08 | 回滚/弃用 | versioning | 可回滚 |
| M2.5-09 | 离线 authoring | authoring tool | 仅 T3、沙箱、人工审核 |
| M2.5-10 | 冷启动指标 | dashboard | Novelty/Hit/Conversion/Backlog |

### 4.7 M3 · Agent 编排

| ID | 任务 | 交付 | 验收 |
|---|---|---|---|
| M3-01 | LangGraph 状态机 | graph | 固定主干 + 条件分支 |
| M3-02 | 修复循环 | repair node | 预算内、可终止 |
| M3-03 | checkpoint/续跑 | checkpointer | 断点恢复 |
| M3-04 | 批量 API | `POST /v1/batches` | 幂等、可查询 |
| M3-05 | 上下文预算 | `assemble_context` | 12–24K/任务 |
| M3-06 | compaction | `compact_context` | 证据不压缩 |
| M3-07 | `load_artifact` | 回读工具 | 指针可回读 |
| M3-08 | trace/成本 | Langfuse | 阶段耗时/成本 |
| M3-09 | 人工中断 | interrupt | 可恢复 |
| M3-10 | 压测 | load report | 30 页 p95 ≤5 分钟 |

### 4.8 M4 · 人机协同

| ID | 任务 | 交付 | 验收 |
|---|---|---|---|
| M4-01 | 复核工作台 | UI | PDF 高亮 + JSON diff |
| M4-02 | 字段 accept/edit/reject | review API | 事件可追溯 |
| M4-03 | 批次复核 | batch UI | 队列、筛选 |
| M4-04 | 修正回流 | feedback dataset | 进入训练/回归 |
| M4-05 | 审计报告 | `audit.md` | 证据、缺口、冲突 |
| M4-06 | RBAC/审计日志 | auth | 角色/操作可查 |
| M4-07 | 主动学习 | sampling | 优先送可疑样本 |
| M4-08 | silent error 审计 | 50 份抽样 | 数值静默错误=0 |

### 4.9 M5 · 生产化

| ID | 任务 | 交付 | 验收 |
|---|---|---|---|
| M5-01 | K8s 部署 | manifests | 可滚动升级 |
| M5-02 | GPU 池隔离 | pools | 生产/探索不互扰 |
| M5-03 | 监控告警 | dashboards | 任务/队列/GPU/成本 |
| M5-04 | SLA | SLO 文档 | 99.5% |
| M5-05 | 备份恢复 | runbook | 演练通过 |
| M5-06 | 灰度/回滚 | release | 可回滚 |
| M5-07 | 安全评审 | report | 无高危 |
| M5-08 | 标准族扩展 | 5 族 | 验收通过 |

---

## 5. 并行轨道

| 轨道 | 负责 | 主要工作 | 关键依赖 |
|---|---|---|---|
| A 文档 AI | 文档 AI 工程师 | OCR、TableGrid、Outline、Coverage、引用 | GLM-OCR 可用 |
| B 抽取/ML | ML 工程师 + 文档 AI | schema、prompt、guided JSON、微调、评测 | 黄金集 |
| C 平台 | 后端/Infra | API、队列、存储、状态机、部署 | 契约 |
| D 领域/评测 | 领域专家 + QA | schema、规则、标注、验收、配方审批 | 业务输入 |

**协作纪律**

- 契约先于实现：Pydantic 契约签字后再写业务逻辑；
- 黄金集先于模型：没有标注不调 prompt；
- 评测先于优化：每次改动必须跑回归；
- 领域专家不缺席：schema、规则、配方晋升必须签字。

---

## 6. 第一轮迭代（垂直切片）

### 6.1 目标

用 **GB/T 1591-2018、GB/T 40303-2021、Q-Du 302-2015** 三份文档跑通：

```text
upload → OCR → TableGrid → extract → normalize → L0–L2 → result/evidence/audit
```

不做微调、不做复杂 Agent、不做复核 UI、不做全量引用闭包。

### 6.2 任务清单

- [ ] 创建仓库骨架、CI、Docker Compose（Postgres/MinIO/Redis）。
- [ ] 定义 Pydantic 契约：`DocumentProfile`、`TableGrid`、`Record`、`Evidence`、`AuditReport`。
- [ ] 实现 `POST /v1/jobs`、`GET /v1/jobs/{id}`、artifact 存储。
- [ ] 接入 GLM-OCR（本地 vLLM；dev 用 mock）。
- [ ] 解析 HTML 表格 → TableGrid：rowspan/colspan、表头树、单位、脚注。
- [ ] 表画像分类 v0：chemical_composition / mechanical_properties / inspection。
- [ ] Qwen3.5-9B zero-shot 抽取，guarded by JSON Schema。
- [ ] 归一化：`0.000 03`、`不大于`、区间、单位、`σb→Rm`、`σ0.2→Rp0.2`、`δs→A`。
- [ ] L0 Schema 校验、L1 证据校验、L2 领域规则（上下限/区间/单位）。
- [ ] 证据写入：page、table、row、col、quote、bbox。
- [ ] 生成 `result.json`、`evidence.jsonl`、`audit.md`。
- [ ] CLI `docparse run --doc ... --schema ... --out ...`。
- [ ] 3 份迷你黄金集（单元格级）+ 评测脚本。
- [ ] 跑 3 份文档，输出错误分布报告。

### 6.3 Demo 脚本（验收演示）

1. 上传 GB/T 40303-2021 PDF。
2. 展示页图 + OCR Markdown。
3. 展示表 2 的 TableGrid（3 个“级别”块、27 个元素）。
4. 展示表画像 + 抽取计划。
5. 展示化学成分记录 + 每个值的证据。
6. 展示 L0–L2 报告与覆盖状态。
7. 导出 `result.json` + `evidence.jsonl` + `audit.md`。
8. 重复 GB/T 1591（困难表头）与 Q-Du 302（方向/状态）。

### 6.4 第一轮验收

- 3 份文档端到端可跑；
- 每个数值有证据指针；
- 简单表核心字段 ≥85%；
- 困难表单独报告，不掩盖；
- 错误分类清楚：OCR / 表格结构 / 表头映射 / 归一化 / 语义 / 引用；
- 不出现“模型猜值”；
- 运行可重复：同一输入同一条路径。

---

## 7. 数据与评测

### 7.1 黄金集

| 维度 | 要求 |
|---|---|
| 数量 | 20 份：8 份数字原生 + 12 份扫描件 |
| 文档类型 | GB/T、GJB、企业规范、技术/采购协议、分类标准 |
| 表类型 | 化学成分、力学性能、检验规则、尺寸偏差、牌号分类 |
| 标注粒度 | 单元格级 + 条款级 |
| 标注字段 | raw、value、unit、comparator、condition、evidence、status |
| 一致性 | 双人标注 + 争议仲裁 |

### 7.2 指标

| 指标 | 定义 | 目标 |
|---|---|---|
| Field Accuracy | 字段值正确 / 字段总数 | M1 简单表 ≥85%，扫描 ≥75%；M2 ≥95% |
| Record F1 | `(grade, condition, property)` 匹配 | ≥95% |
| Header Mapping | 列角色/属性/单位映射正确率 | ≥98% |
| Coverage Rate | 有证据或明确 missing/ambiguous 的必填字段 / 必填字段 | ≥95% |
| Locator Accuracy | 命中预期条款/表的字段 / 计划字段 | ≥90% |
| Clause F1 | 方法/方向/位置/数量/温度/判定 | ≥90% |
| Link Accuracy | 表-条款链接正确率 | ≥95% |
| Orphan Rate | 无牌号/条件的行 / 总行数 | <1% |
| Hallucination | 无证据的值 / 发布值 | <1% |
| STP | 无人工修改直接发布 / 总文档 | ≥80% |
| Human Minutes | 人工复核分钟 / 文档 | M4 下降 ≥50% |

### 7.3 基线

- 人工基线：领域专家逐字段抽取，记录耗时与错误；
- 商用基线：2 家智能体，同一批文档、同一 schema，字段级 P/R/F1；
- 本地 zero-shot：Qwen3.5-9B + guided JSON；
- 本地微调：M2 后同批对比；
- 所有基线都要记录：版本、prompt、输入格式、耗时、成本。

### 7.4 回归

- 每次 prompt/recipe/model 变更跑黄金集；
- 输出 diff：新增错误、修复错误、覆盖变化；
- 核心字段下降 >1 个百分点 → 阻止合并；
- 生产失败案例自动进入回归集。

---

## 8. 模型与部署

### 8.1 GLM-OCR

- 本地 vLLM 部署，按页输出 Markdown/HTML；
- 保留页图、页码、bbox；
- 页级重试：低质量页裁剪重 OCR；
- 备选：PaddleOCR-VL / MinerU，不作为主路径；
- 版本写入 `result.json`。

### 8.2 Qwen3.5-9B

- vLLM 部署，guided JSON；
- 32K 上下文；表单任务 12–24K；
- 两阶段：表头映射 → 行记录；
- LoRA 适配器可选，按任务/标准族拆分；
- 模型注册表：base、adapter、prompt、schema 版本。

### 8.3 GPU 与队列

| 池 | 用途 | 隔离 |
|---|---|---|
| OCR 池 | 页级识别 | 生产优先 |
| 抽取池 | 表级抽取 | 生产/探索分配额 |
| 探索池 | Agent-first、authoring | 不阻塞生产 |

- dev 用 mock，不占 GPU；
- staging 单卡；
- prod 按峰值页/天测算，保留 30% 余量；
- 每个任务记录 GPU 秒数/成本。

### 8.4 回退

- OCR 失败 → 裁剪重 OCR → 人工；
- 抽取失败 → 修复重试 → 教师模型/更大模型 → 人工；
- 配方不匹配 → 表级探索；
- 引用缺失 → `reference_gap`，不自动发布。

---

## 9. 质量体系与 Definition of Done

### 9.1 校验层级

| 层 | 内容 | 失败动作 |
|---|---|---|
| L0 Schema | JSON Schema、类型、必填 | 重解码/修复 |
| L1 证据 | 每个值有页/表/行/列/quote | 标 `needs_evidence` |
| L2 领域规则 | 上下限、区间、单位、比较符 | 修复/升级 |
| L3 交叉一致 | 表间、正文、脚注、跨页 | 标记冲突 |
| L3.5 覆盖 | 必填字段、孤儿行、表-条款 | 定向检索/人工 |
| L4 LLM Judge | 语义支持（仅可疑字段） | 修复/升级 |
| L5 人工 | 复核/签字 | 发布/拒绝 |

### 9.2 DoD

**代码**

- 单元测试覆盖核心解析/归一化；
- 契约测试通过；
- lint/type check 通过；
- 无裸 `except`、无静默失败。

**数据**

- schema 校验通过；
- 证据覆盖率达标；
- 无孤儿行；
- 版本/来源可追溯。

**模型**

- held-out 评测达标；
- 回归无下降；
- 幻觉率达标；
- 模型/prompt/schema 版本记录。

**配方**

- L2 合同测试 + 金样例；
- L3 影子 + 人工签字；
- L4 版本、适用范围、限制、回滚。

**发布**

- 审计包完整；
- 回滚演练通过；
- runbook 更新；
- 变更记录。

---

## 10. 冷启动与运营

### 10.1 Router

- 输入：前几页、表头、标题层级、引用样式、扫描质量；
- 输出：`production` / `explore` / `human` + 置信度 + 原因；
- 粒度：表级，不是整份文档；
- 误判成本：生产误判 → 回退；探索误判 → 浪费预算；人工误判 → 延迟。

### 10.2 三条队列

| 队列 | 内容 | 目标 |
|---|---|---|
| 生产 | active 配方 | 吞吐/稳定/审计 |
| 探索 | 未知/低置信 | 候选配方/测试样例 |
| 人工 | 高风险/歧义/审批 | 判断/签字/例外 |

### 10.3 配方晋升

```text
L0 unknown → L1 explored → L2 candidate → L3 shadow → L4 active → L5 deprecated
```

- L2：合同测试 + 3–10 金样例 + 表头映射 ≥98%；
- L3：同族影子 + 覆盖 ≥95% + 一致 ≥98% + 无孤儿行；
- L4：人工签字 + 版本/范围/限制/回滚；
- 探索结果永不直接发布。

### 10.4 冷启动指标

| 指标 | 目标 |
|---|---|
| Novelty Rate | 逐步 <20% |
| Recipe Hit Rate | ≥80% |
| Conversion Rate | 持续 > 新格式出现率 |
| Human Minutes/Doc | M4 下降 ≥50% |
| Production STP | ≥80% |
| Exploration Backlog | 有界、稳定 |

### 10.5 运营节奏

- 按批次处理，不逐份人工分诊；
- 高频族优先，一次性文档不强行做配方；
- 每周看 Novelty/Hit/Backlog/STP；
- 每月复盘错误 Top 5 与配方覆盖；
- 标准换版触发配方复审。

---

## 11. 风险与应对

| 风险 | 触发信号 | 影响 | 应对 | 归属 |
|---|---|---|---|---|
| 扫描件 OCR 质量 | 低文本页、乱码、表格线丢失 | 上游错，全链错 | 页级质量评分、裁剪重 OCR、人工 | 文档 AI |
| 表格结构复杂 | 多层表头、跨页、转置 | 列映射错 | TableGrid + 几何回退 + 金样例 | 文档 AI |
| 引用版本漂移 | 不注日期引用、标准换版 | 抽错版本 | 版本表 + `resolution_basis` + 人工 | 领域 |
| 配方覆盖不足 | Novelty 高、Backlog 增长 | 直通率低 | 高频族优先、通用配方、Router | 产品/领域 |
| 配方过拟合 | 同族换文档即崩 | 隐性错误 | 聚类代表、影子、签名约束 | 文档 AI |
| 数值幻觉 | 无证据值、异常值 | 材料误判 | 证据链、L2、L4、审计抽样 | 抽取/QA |
| 微调数据不足 | 长尾样本少 | 过拟合 | 教师蒸馏、合成扰动、留出集 | ML |
| GPU 容量不足 | 队列积压、延迟上升 | SLA 不达标 | 池隔离、配额、扩容 | Infra |
| 复核工作量大 | 人工分钟数不降 | 负收益 | 置信度路由、批量复核、主动学习 | 产品 |
| 范围蔓延 | “全条款/全表格”需求 | 交付失控 | 首期 schema 必填字段为准；二期再扩 | 技术负责人 |

---

## 12. 交付物清单

| 类别 | 交付物 |
|---|---|
| 代码 | API、worker、CLI、UI、infra |
| 契约 | Pydantic + JSON Schema + 版本 |
| 数据 | 黄金集 v0/v1、标注规范、训练集 |
| 模型 | GLM-OCR 部署、Qwen adapter、模型卡 |
| 配方 | 21–35 个配方、注册表、影子报告 |
| 评测 | 基线报告、回归报告、审计抽样 |
| 文档 | 架构、API、Schema、Runbook |
| 运维 | Compose/K8s、监控、告警、备份 |
| 交付 | result.json、evidence.jsonl、audit.md |

---

## 13. 待确认决策

| # | 决策 | 影响 | 建议默认 | 负责人 |
|---|---|---|---|---|
| 1 | 首期“完整”定义：schema 必填字段 vs 全规范性条款 | 范围/工作量 | schema 必填字段 | 业务 + 技术 |
| 2 | 首期三份文档是否确认 | 打样范围 | GB/T 1591、GB/T 40303、Q-Du 302 | 业务 |
| 3 | 黄金集 20 份清单 | 评测有效性 | 8 数字 + 12 扫描，覆盖 4 类 | 领域 |
| 4 | 本地 GPU 容量/型号 | 部署/成本 | 按峰值页/天测算 | Infra |
| 5 | GLM-OCR/Qwen 版本 | 结果稳定性 | 固定版本，写入结果 | ML |
| 6 | 首期是否做复核 UI | 交付范围 | 首期 API/CLI，M4 做 UI | 产品 |
| 7 | 是否允许自动发布 | 风险 | M3 前不自动；M4 后按闸门 | 业务 |
| 8 | 技术协议/采购/分类标准是否首期 | 模板投入 | 各 1 份验证，其余人工 | 业务 |
| 9 | 转置表是否自动识别 | 表方向 | 自动 + 低置信人工 | 文档 AI |
| 10 | 验收阈值是否按本计划 | 验收 | 按 M0–M5 表 | 业务 + QA |

> 与方案第 11 章的 Q1–Q41 对应；本表只列开发启动前必须确认的 10 项。

---

## 14. 确认后的下一步

| # | 动作 | 负责人 | 输出 |
|---|---|---|---|
| 1 | 开 M0 启动会，确认范围/阈值 | 技术负责人 | 会议纪要 + 签字 |
| 2 | 冻结 Schema v0 | 文档 AI + 领域 | `schemas.md` |
| 3 | 选 20 份黄金集 | 领域 + QA | `goldset/v0/manifest.json` |
| 4 | 建仓库/CI/Compose | 后端 + Infra | 可运行骨架 |
| 5 | 部署 GLM-OCR + Qwen | Infra | 本地服务 + smoke test |
| 6 | 实现 3 份文档垂直切片 | 文档 AI + 后端 | demo |
| 7 | 跑人工/商用基线 | 领域 + QA | baseline report |
| 8 | M1 go/no-go 评审 | 技术负责人 | 进入 M1.5 或修解析 |

---

## 附录 A · 任务状态字段

每个任务在项目管理工具中使用以下字段：

```text
id, epic, milestone, title, owner, priority(P0/P1/P2),
depends_on, deliverable, acceptance, status(todo/doing/blocked/done),
evidence_link, risk, created_at, updated_at
```

状态规则：

- `blocked` 必须写阻塞原因与解除条件；
- `done` 必须附验收证据链接；
- 没有 acceptance 的任务不允许开工；
- 跨里程碑依赖变更必须记录在决策日志。

## 附录 B · API/CLI 契约（首期）

```text
POST /v1/jobs                 上传 PDF，创建任务
GET  /v1/jobs/{id}            任务状态、阶段、错误
GET  /v1/jobs/{id}/result     result.json
GET  /v1/jobs/{id}/evidence   evidence.jsonl
GET  /v1/jobs/{id}/audit      audit.md
POST /v1/jobs/{id}/review     人工复核（M4）
GET  /v1/recipes              配方列表
POST /v1/recipes/{id}/shadow  影子运行（M2.5）
POST /v1/recipes/{id}/promote 晋升（M2.5）
```

```bash
docparse run \
  --doc "标准文件/GBT 1591-2018/..." \
  --schema schemas/product_full.yaml \
  --out runs/gbt1591 \
  --profile product_full
```

输出：

```text
runs/gbt1591/
├─ result.json
├─ evidence.jsonl
├─ audit.md
├─ tablegrid/
├─ outline.json
├─ coverage_plan.json
└─ trace.json
```

---

## 附录 C · 首个里程碑检查清单

- [ ] 范围与验收阈值签字
- [ ] Schema v0 可映射 20 份文档
- [ ] 黄金集 v0 清单冻结
- [ ] 标注规范双人一致性 ≥90%
- [ ] 人工基线报告
- [ ] 商用基线报告（2 家）
- [ ] GLM-OCR 本地 smoke test
- [ ] Qwen guided JSON smoke test
- [ ] 仓库/CI/Compose 可用
- [ ] M1 三份文档 demo 可重复
- [ ] 错误分布报告
- [ ] M1 go/no-go 评审
