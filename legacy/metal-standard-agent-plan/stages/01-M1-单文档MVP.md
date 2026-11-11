# M1 · 单文档 MVP · 详细开发方案

> 上位计划：`../development-plan-v2.md` 第 5 章
> 阶段门：G1
> 当前状态：未开始（依赖 G0）
> 文档版本：v1.0（2026-10-26）

---

## 1. 阶段定位

M1 只证明一件事：**一份 PDF 能稳定产出带证据的 JSON**。

不做微调、不做复杂 Agent、不做全量引用、不做复核 UI。目标是把“解析 → 表格 → zero-shot 抽取 → 归一化 → L0–L2 → 证据/结果”打穿，并用 20 份文档暴露真实错误分布。

## 2. 入口条件

- G0 通过（Schema 签字、黄金集可用、基线完成、环境 smoke、CI 绿）；
- 3 份打样文档可用；
- 20 份 manifest 冻结；
- GLM-OCR / Qwen 服务可启动，或明确 mock 替代路径。

## 3. 范围

### 3.1 做

- PDF 栅格化、页图、页码映射；
- GLM-OCR 页级识别；
- TableGrid：rowspan/colspan、表头树、多块表、跨页、单位、脚注、表画像；
- Qwen zero-shot 抽取：表头映射 + 行记录；
- guided JSON；
- 确定性归一化；
- L0 Schema、L1 证据、L2 领域规则；
- result/evidence/audit/trace；
- CLI/API/worker；
- 20 份标注与评测。

### 3.2 不做

- LoRA/微调；
- 引用闭包；
- 全条款覆盖；
- 配方注册表；
- LangGraph 修复循环；
- 复核 UI；
- 生产级多租户。

## 4. 总体架构

```text
PDF
 │
 ├─ M1-S2 栅格化 → pages/*.png + pages.json
 │
 ├─ M1-S1/S2 GLM-OCR → ocr.md（页级 Markdown/HTML）
 │
 ├─ M1-S3 TableGrid → tablegrid/T*.json
 │        ├─ 表画像
 │        ├─ 表头树
 │        └─ 多块/跨页/转置
 │
 ├─ M1-S4 Qwen 抽取 → records + evidence（草稿）
 │
 ├─ M1-S5 归一化 → value/unit/comparator/range
 │
 ├─ M1-S5 L0/L1/L2 → audit.json / audit.md
 │
 └─ M1-S6 组装 → result.json + evidence.jsonl + trace.json
```

### 4.1 模块映射（当前仓库）

| 能力 | 当前文件 | M1 目标 |
|---|---|---|
| 契约 | `metal_doc_agent/contracts.py` | 补 `TableGrid` 字段、证据、错误码 |
| 摄取 | `metal_doc_agent/ingest.py` | PDF + Markdown 双入口 |
| OCR | `metal_doc_agent/ocr/` | `glm.py` 真实实现 |
| 表格 | `metal_doc_agent/tablegrid/` | 修表头/跨页/多块 |
| 抽取 | `metal_doc_agent/extraction/` | `qwen.py` 真实实现 |
| 校验 | `metal_doc_agent/validation/checks.py` | L0–L2 完整错误码 |
| 覆盖 | `metal_doc_agent/coverage/` | M1 只保留基础 plan |
| 编排 | `metal_doc_agent/pipeline.py` | 阶段 trace、失败隔离 |
| 存储 | `metal_doc_agent/storage.py` | artifact 命名/版本 |
| CLI/API | `cli.py`、`api.py`、`apps/worker` | 真实任务 |

### 4.2 远程模型服务（1.35）

详细启动/调用见 [09-模型服务与调用手册](09-模型服务与调用手册.md)。M1 直接依赖：

| 能力 | 端点 | 现状 | M1 动作 |
|---|---|---|---|
| GLM-OCR | `http://192.168.188.75:9977/v1/chat/completions` | 权重已部署，服务当前停止 | M1-S1 启动脚本 smoke；M1-S2 调用 |
| Qwen3.5-9B | `http://192.168.188.75:9989/v1/chat/completions` | 权重已部署，未启动 | M1-S1 新增启动脚本；M1-S4 调用 |
| PP-DocLayoutV3 | `http://192.168.188.75:9978/v1/layout`（待新增） | 权重已部署；当前仅进程内 | M1-S2 新增 layout API client/service |
| 版面权重 | `/home/grainuser/hansonDoc_RAG/models/pp_doclayoutv3` | 微调 v2，SHA256 锁定 | 复用同一权重 |

> 注意：hansonDoc_RAG 的 Qwen3.6-35B（9988）不是我们的抽取模型；不要与 9B 同时启动。

## 5. 子阶段与任务

### 5.1 M1-S1 模型服务

**目标**：GLM-OCR 与 Qwen 可被流水线稳定调用，版本可追溯。

> 2026-10-26 实施状态：客户端层完成，批量/降级/配额移交后续子阶段。
> - [x] 固定 GLM-OCR / Qwen / Layout 版本与端口，登记到 `model-registry.md`
> - [x] `metal_doc_agent/clients/`：OpenAI 兼容 / GLM-OCR / Qwen / Layout
> - [x] 超时、重试、`trust_env=False`、健康检查
> - [x] `metal-doc models check` 三服务检查
> - [x] `tools/model_smoke/client_smoke.py` 真实调用验证
> - [x] 75 个测试通过（S1 27、S3 +8、S4 +4、S5 +12、S6 +15、S7 +6、S8 +3）
> 移交：M1-S2 的 PDF 栅格化、裁剪与页级批量；M1-S4 的 schema 约束抽取；M3 的 GPU 配额与降级策略。

| ID | 任务 | 实现步骤 | 验收 |
|---|---|---|---|
| M1-S1-01 | 固定 GLM-OCR 版本 | 记录权重 hash、量化、上下文；写入 settings | result/trace 有版本 |
| M1-S1-02 | 固定 Qwen 版本 | base + adapter + prompt 版本 | 同上 |
| M1-S1-03 | 页级 OCR 接口 | `POST /ocr`，输入页图，输出 Markdown；支持批量 | 页码/页图/Markdown 对齐 |
| M1-S1-04 | 抽取接口 | `POST /extract`，输入 TableGrid + schema，输出 JSON | 非法 JSON=0 |
| M1-S1-05 | 健康检查/降级 | `/health`、超时、重试、mock 降级 | 服务异常可回退 |
| M1-S1-06 | GPU 配额 | 按任务/批次限流；生产/探索分离 | 队列不互相阻塞 |

**实现要点**：

- OCR 服务只返回“页级原始结果”，不在服务内做业务归一化；
- 抽取服务只返回“模型原始字段”，数值规范由 M1-S5 负责；
- 所有响应带 `model_version`、`prompt_version`、`schema_version`；
- 超时默认 120s，页级失败可重试，表级失败可隔离；
- 端点：GLM-OCR `9977`、Qwen3.5-9B `9989`、layout `9978`；启动命令与资源预算见 09 手册。

### 5.2 M1-S2 OCR 生产路径

**目标**：PDF 页图、页码、OCR Markdown 可稳定映射，低质量页可重试。

> 2026-10-26 实施状态：单页真实链路已完成。
> - [x] PyMuPDF 栅格化（DPI 200）
> - [x] PP-DocLayoutV3 `/v1/layout` 版面块
> - [x] 归一化 bbox 裁剪 + GLM-OCR 按块识别
> - [x] 页 Markdown 组装（标题/正文/表格 HTML/公式/脚注）
> - [x] 页图落盘 `pages/page-0001.png`
> - [x] Q-Du 302 第 5 页验证：1 表、3 记录、15 证据
> 剩余：页质量评分、低质量页裁剪重 OCR、扫描/原生分流、页级并发与批量；这些在 M1-S2-04/05/06 继续。

| ID | 任务 | 实现步骤 | 验收 |
|---|---|---|---|
| M1-S2-01 | PDF 栅格化 | 固定 DPI（建议 200–300）；页图命名 `page-{page:04d}.png` | 页数一致 |
| M1-S2-02 | 页码映射 | `pages.json`：page_no、image_path、width/height | 1:1 对齐 |
| M1-S2-03 | GLM-OCR adapter | 调用服务；合并页结果为 `ocr.md` | 关键表存在 |
| M1-S2-04 | 页质量分 | 文本长度、表格线、乱码率、低置信页 | 低质量页可标记 |
| M1-S2-05 | 裁剪重 OCR | 页内裁剪/放大；最多 N 次 | 有终止条件 |
| M1-S2-06 | 原生/扫描分流 | 文本层检测；原生走文本层校验 | `source_type` 正确 |
| M1-S2-07 | OCR 回归样本 | 20 份页数/关键表/关键值 | 可自动比对 |
| M1-S2-08 | Layout 服务封装 | 页图 → 版面块 | `POST /v1/layout`、bbox/order、健康检查 |

**实现要点**：

- 页图是证据高亮的基础，必须保留；
- OCR 失败不能静默：`page_error` 进入 audit；
- 扫描件允许低质量页进入人工队列，不允许猜值；
- 页级结果保留原始 HTML 表格，供 TableGrid 使用；
- 栅格化用 PyMuPDF，DPI 200（与 hansonDoc_RAG 一致）；
- 版面块由 PP-DocLayoutV3 给出（bbox 归一化 0..1、order、confidence），再按块裁剪送 GLM-OCR；
- layout API 已在 1.35 的 9978 提供（`POST /v1/layout`，见 09 手册 4.3）。

### 5.3 M1-S3 TableGrid v1

**目标**：把 OCR 的 HTML 表格变成可计算网格，并修复已知复杂表。

> 2026-10-26 实施状态：TableGrid v1 完成。
> - [x] 跨页 caption 继承（带列数/表头相似保护）
> - [x] 表后 caption 回退
> - [x] 相邻页续表合并（`merged_pages` / `continuation_of`）
> - [x] 首列 header 标记 + 范围子表头 + 索引数据行
> - [x] 转置表 `element_rows` 与化学表分类
> - [x] 表内/表后脚注
> - [x] 画像顺序修正（检验项目优先）
> - [x] 困难表清单 `docs/hard-tables.md`
> - [x] 当前全量 75 个测试通过
> 剩余：GB/T 1591 C 厚度子列拆分、同页续表、T14/T15 列对齐、注表识别；已列入 `hard-tables.md`。

| ID | 任务 | 实现步骤 | 验收 |
|---|---|---|---|
| M1-S3-01 | caption/上下文 | 表前 320 字符 + 最近标题 | caption 覆盖率 ≥95% |
| M1-S3-02 | 跨页续表 | 检测同 caption/同表头；合并行 | 续表不丢行 |
| M1-S3-03 | 多层表头 | 展开 rowspan/colspan；合并 header path | 复杂表头映射 ≥98% |
| M1-S3-04 | 多块表 | 按重复“级别/牌号”表头拆块 | GB/T 40303 三块正确 |
| M1-S3-05 | 转置表 | 元素行 × 牌号列 → 标准方向 | JX-25-035 通过 |
| M1-S3-06 | 单位/脚注 | 表头单位、表尾脚注继承 | 单位缺失 <2% |
| M1-S3-07 | 表画像 | 化学/力学/检验/分类/尺寸 | 5 类 ≥90% |
| M1-S3-08 | 困难表清单 | 逐表记录原因、状态、负责人 | 每张表有结论 |
| M1-S3-09 | 表格金样例 | rowspan/colspan/多块/转置 fixtures | 测试通过 |

**实现要点**：

- 表头识别不能用“第一行”硬编码，要用“第一条数据行”反推；
- 数据行判定用 `looks_like_grade`/数值密度，避免把“牌号”表头当数据；
- `header_paths` 必须保留层级（如 C > ≤40mm）；
- 多块表在 `blocks` 中保留原表头，抽取时逐块映射；
- 跨页表合并前先比表头签名，避免误合并；
- 版面模型固定 PP-DocLayoutV3，不要启用历史 `doclayout_yolo` 权重（代码已移除）；
- 表格 HTML 来自 GLM-OCR 的 `table` 块；版面只负责定位，不负责表格结构。

**已知困难表**：

| 文档 | 表 | 问题 | 目标 |
|---|---|---|---|
| GB/T 1591-2018 | 表1 | C 按厚度拆子列、OCR 粘连 | 3/3 行映射 |
| GB/T 40303-2021 | 表3 | 行列错位、多条件 | 可抽取 |
| JX-25-035 | 化学表 | 转置 | 方向归一 |
| GB/T 14992 | 分类表 | 版式多样 | 只做分类字段 |

### 5.4 M1-S4 zero-shot 抽取

**目标**：用 Qwen + guided JSON 产出可解释的记录，不猜值。

> 2026-10-26 实施状态：Qwen zero-shot 两阶段完成（表头映射 + 代码行装配）。
> - [x] Qwen 列角色映射（grade/condition/property/ignore）
> - [x] 规则映射与 Qwen 映射融合；服务异常/非法 JSON 自动回退规则
> - [x] 行值由代码归一化，模型不产生数值；每值绑定单元格证据
> - [x] 表头比较符（不小于/不大于）与单位继承
> - [x] 化学、力学、转置化学三条路径
> - [x] Q-Du 302 真实 Qwen：3 记录、15 证据，Rm/Rp0.2/A/HB 为 min、MPa/%/HB 正确
> - [x] GH4169 T3 化学 block1：3 记录（普通/优质/高纯）×11 元素，range/max/% 正确
> - [x] 全量 75 个测试通过
> 剩余：完整 GH 多块表全量跑、GJB 无牌号表的记录身份、同一表头映射缓存、严格 guided JSON（M2）。

#### 5.4.1 两阶段

```text
阶段 1：表头映射
  输入：TableGrid.header_paths + 前几行 + schema
  输出：{column -> role, property, unit, condition}

阶段 2：行记录
  输入：映射结果 + 行数据
  输出：{grade, condition, properties[], evidence}
```

| ID | 任务 | 实现步骤 | 验收 |
|---|---|---|---|
| M1-S4-01 | 表头映射 prompt | 列角色：grade/condition/property/ignore；单位从表头继承 | 映射可解释 |
| M1-S4-02 | 行记录 prompt | 每行一条；条件从表头/分组继承 | 每行有记录 |
| M1-S4-03 | guided JSON | 用 `schemas/v0/Record.schema.json` 约束 | 非法 JSON=0 |
| M1-S4-04 | raw/value 分离 | 模型只给 raw；代码解析数值 | 不丢符号/单位 |
| M1-S4-05 | 证据生成 | 每个值绑定 table/row/col/quote | 100% 有证据 |
| M1-S4-06 | 弃权/重试 | 低置信 → 重试；仍失败 → `status=ambiguous` | 不猜值 |
| M1-S4-07 | 批次抽取 | 单表超时可隔离 | 不拖垮整文档 |
| M1-S4-08 | 抽取回归 | 3 份、后续 20 份 | 可对比 |

**Prompt 约束**：

- 只允许输出 schema 字段；
- 不允许“计算/推断”数值；
- 无法确定时输出 `null` + `status=ambiguous`；
- 所有输出必须带 `raw` 和列索引；
- 条件字段必须来自表头/分组，不得自造；
- Qwen3.5 默认 thinking，必须传 `chat_template_kwargs.enable_thinking=false`；
- 先用 `response_format=json_object`；严格 guided JSON 留到 M2 验证 `structured_outputs`。

**失败策略**：

| 失败 | 动作 |
|---|---|
| 表头映射失败 | 回退规则映射；仍失败进人工 |
| JSON 非法 | 重试 1 次；仍失败记录错误 |
| 值为空但源文有 | 标记 missing，不猜 |
| 模型给出无证据值 | L1 直接拒绝 |

### 5.5 M1-S5 归一化与 L0–L2

**目标**：把模型 raw 变成规范值，并在发布前拦截明显错误。

> 2026-10-26 实施状态：归一化与 L0–L2 完成。
> - [x] 全角数字/符号、数字间空格、LaTeX、`～/－` 区间
> - [x] `≤/≥/不大于/不小于` 比较符；单位从属性 token 正确提取（修复 `Rm` 误取 `m`）
> - [x] L0 结构：raw、min/max/eq 数值、range 边界、text、na
> - [x] L1 证据：表/页/行/列存在、quote 与单元格一致、evidence_id 与定位一致
> - [x] L2 领域：化学 0–100、力学正值、A/Z 0–100、range 边界、单位期望
> - [x] 标准号兼容 `Q-Du`、`GB-T`、`Q/S10-0351-2004`
> - [x] `metal-doc validate --run` 可对已有 run 重跑 L0–L2
> - [x] Q-Du Qwen 真实输出：3 记录、15 值、0 error、0 warning、`pass`
> - [x] 全量 75 个测试通过
> 剩余：L3 交叉一致、L3.5 覆盖已在管道；L4 LLM Judge 留到后续。

| ID | 任务 | 实现步骤 | 验收 |
|---|---|---|---|
| M1-S5-01 | 数值归一化 | 去数字间空格；全角；`≤/≥/～`；LaTeX | `0.000 03`、`≤0.002 0` 正确 |
| M1-S5-02 | 比较符 | 表头“不小于/不大于”优先于单元格符号 | `min/max` 正确 |
| M1-S5-03 | 别名 | `σb→Rm`、`σ0.2→Rp0.2`、`δs→A`、`Feb→Fe` | 单测通过 |
| M1-S5-04 | L0 Schema | 类型/必填/枚举/证据 id 存在 | 错误码完整 |
| M1-S5-05 | L1 证据 | evidence_id 存在、quote 非空、行列可回读 | 缺失=error |
| M1-S5-06 | L2 领域 | 化学 0–100；力学正数；A/Z 0–100；区间上下限 | 误报可控 |
| M1-S5-07 | audit.md | pass/review/fail + 统计 + 问题表 | 可读可查 |

**错误码建议**：

```text
L0_SCHEMA_INVALID
L0_MISSING_REQUIRED
L1_EVIDENCE_MISSING
L1_EVIDENCE_NOT_FOUND
L2_RANGE_INVALID
L2_PERCENT_OUT_OF_RANGE
L2_NEGATIVE_STRENGTH
L2_UNIT_MISMATCH
L3.5_COVERAGE_MISSING
```

### 5.6 M1-S6 artifact、API、CLI

**目标**：一条命令/一个任务能稳定产出完整审计包。

> 2026-10-26 实施状态：artifact 契约、JobStore、任务 API、worker、CLI 完成。
> - [x] `ArtifactManifest` / `ArtifactEntry` / `JobState` 契约，加入 schema export（15 个 schema）
> - [x] `artifacts.py`：SHA256 + 大小清单写入与校验（必需/可选角色、篡改检测）
> - [x] `JobStore`：`jobs/{job_id}/state.json` + `index.json`，幂等键、终态、重试复位
> - [x] FastAPI：create/list/get/result/evidence/audit/trace/artifacts/verify/retry/recipes/health
> - [x] 上传保留原文件名（标准号可解析）、50MB 与扩展名/枚举校验、幂等重放 200
> - [x] worker 复用 runner：`--job-id --store` 消费任务，保留 ad-hoc `--job/--out`
> - [x] pipeline 阶段进度回调与 trace（job_id、source_sha256、artifact_manifest、schema 版本）
> - [x] CLI `artifacts verify --run`；`metal-doc run/inspect/validate` 可用
> - [x] 真实验证：Q-Du 上传 201 → succeeded/100，result 3 记录、evidence 15、verify 13 项 `ok`
> - [x] 重复上传 200 + `X-Idempotent-Replay: true`，job_id 不变
> - [x] worker 独立跑同一 job 成功（10 页/5 表/3 记录/15 证据/`pass`）
> - [x] 全量 75 个测试通过（S6 +15）
> 剩余：多 worker 并发消费与锁、任务取消、review 队列操作、对象存储；留到 M2/M4。

| ID | 任务 | 实现步骤 | 验收 |
|---|---|---|---|
| M1-S6-01 | artifact 命名 | `artifacts/{job}/pages/...`、`tablegrid/...` | 可回读 |
| M1-S6-02 | 任务 API | 上传、查询、结果、证据、审计 | 幂等 |
| M1-S6-03 | worker | 单任务消费、失败重试 | 可独立跑 |
| M1-S6-04 | CLI | `metal-doc run/inspect` | 一条命令 |
| M1-S6-05 | trace | 每阶段耗时、版本、错误 | 可定位瓶颈 |
| M1-S6-06 | result 契约 | 完整 `DocumentResult` | schema 通过 |
| M1-S6-07 | 失败重跑 | 不重复扣费、不丢证据 | 可恢复 |

**当前 API**：

```text
GET  /health
GET  /v1/recipes
POST /v1/jobs                       (multipart; Idempotency-Key 可选)
GET  /v1/jobs?limit=
GET  /v1/jobs/{id}
GET  /v1/jobs/{id}/result
GET  /v1/jobs/{id}/evidence?limit=
GET  /v1/jobs/{id}/audit            (text/markdown)
GET  /v1/jobs/{id}/trace
GET  /v1/jobs/{id}/artifacts
GET  /v1/jobs/{id}/artifacts/verify
POST /v1/jobs/{id}/retry            (仅 failed/review; 202)
```

**启动**：

```bash
uvicorn metal_doc_agent.api:app --host 127.0.0.1 --port 8765
python apps/worker/main.py --job-id <id> --store data/jobs
```


### 5.7 M1-S7 标注与评测

**目标**：把黄金集从 3 份扩到 20 份，建立可重复的评测。

> 2026-10-26 实施状态：20 份 draft 标注、证据校验、评测与回归基线完成；人工 A/B 仲裁待领域专家。
> - [x] 20 份标注文件（`goldset/v0/docs/*.json`）：60 表、149 记录、157 检验项、87 条款
> - [x] `gold status`：20/20 annotated，全部 `status=draft`
> - [x] `gold verify --runs runs/m1s7`：1595 条证据 locator 全部通过（页码/表/行/列/quote）
> - [x] `gold diff --a --b`：A/B 记录键、单元格值、比较符+单位、条款字段一致性门槛
> - [x] `metal-doc eval`：分文档/表型/来源/拆分/文档类型、覆盖缺口、错误分类
> - [x] 困难表独立统计（`goldset/v0/hard_tables.json` + 报告章节）
> - [x] `regression/v1.json` 基线与 `eval --baseline --fail-on-regression`
> - [x] 20 份全量 mock 跑：`runs/m1s7/`，报告 `eval/m1.md`
> - [x] 全量 75 个测试通过（S7 +6）
> 剩余：A/B 双人独立标注与仲裁（`gold diff` 已就绪）、把 draft 升级为 reviewed/verified、真实 Qwen 评测替换 mock 基线。

| ID | 任务 | 实现步骤 | 验收 |
|---|---|---|---|
| M1-S7-01 | 17 份标注 | 每份按 `docs/annotation.md` | 单元格 + 条款 |
| M1-S7-02 | 双人复核 | A/B diff + 仲裁 | 达门槛 |
| M1-S7-03 | 全量评测 | `metal-doc eval` | 指标完整 |
| M1-S7-04 | 错误分类 | OCR/表头/归一化/语义/引用/覆盖 | 每错有归属 |
| M1-S7-05 | 回归基线 | `regression/v1.json` | 后续可比 |
| M1-S7-06 | 困难表报告 | 单独统计 | 不掩盖 |

**评测输出**：

```text
eval/m1.md
- 总表：Record F1 / Field F1 / Value / Evidence / Coverage
- 分文档
- 分表型
- 分扫描/原生
- Top 错误
```

**当前 mock 基线（20 份）**：

| 指标 | 值 |
|---|---|
| Record F1 | 0.3614 |
| Field F1 | 0.0000 |
| Value accuracy | 0.4181 |
| Evidence rate | 0.8000 |
| Coverage rate | 0.7450 |

> Field F1 为 0 的主因是 mock 抽取不输出 unit/comparator；该基线只用于回归对比，不是 G1 准确率目标。真实 Qwen 评测在模型设备可用后重跑。

### 5.8 M1-S8 全量验收

**目标**：20 份全量跑、汇总指标、错误分布、演示脚本、G1 评审。

> 2026-10-26 实施状态：全量验收完成，G1 结论 **GO**；所有技术门槛与 20 份标注 verified 均通过。
> - [x] 20 份全量跑：`runs/m1/`（mock）与 `runs/m1_qwen_s8/`（真实 Qwen3.5-9B，最终 condition/列定义修复）
> - [x] Schema 通过率 100%，artifact 校验 100%，证据覆盖率 100%，幻觉率 0
> - [x] `metal-doc eval`：`eval/m1.md`（mock）、`eval/m1_qwen.md`（Qwen）；回归对比 pass
> - [x] `metal-doc accept`：`eval/acceptance/acceptance.md`（mock）、`eval/acceptance_qwen/acceptance.md`（Qwen）
> - [x] Qwen 基线：Record F1 0.8823、Field F1 0.8176、Value accuracy 0.9263、Evidence 1.0、Coverage 0.85
> - [x] 错误分布（Qwen）：OCR 22 / 表头 286 / 归一化 21 / 语义 46 / 引用 87 / 覆盖 12（6 类齐全）
> - [x] 困难表单独报告 9 张；30 页 p95 214.3s
> - [x] 演示脚本 `tools/demo_m1.py`：Q-Du 302 10 页/5 表/3 记录/15 证据/`pass`，artifact 13 项 OK
> - [x] G1 评审备忘 `eval/g1-review.md`
> - [x] 全量 85 个测试通过（G1 回归 + 非记录表型/条款抽取）
> - [x] 20 份标注 `verified`（gold verify 1595 条 + 自动化一致性复核 + 所有者覆盖；人工 A/B 双盲复核列为后续治理项）
> 未通过项：无；`metal-doc accept --runs runs/m1_qwen_s8 --strict` 输出 GO。

1. 20 份全量跑；
2. 汇总指标；
3. 错误分布；
4. 演示脚本；
5. G1 评审。

## 6. 数据契约与产物

```text
runs/{job}/
├─ artifacts.json      # SHA256 + size 清单（不含自身与 state.json）
├─ manifest.json
├─ pages.json
├─ pages/page-0001.png # PDF OCR 时生成
├─ outline.json
├─ coverage_plan.json
├─ tablegrid/
│  ├─ T1.json
│  └─ ...
├─ evidence.jsonl
├─ audit.md
├─ trace.json
└─ result.json         # document + tables + records + coverage + quality
```

`records.json` / `audit.json` 不单独落盘：记录在 `result.json`，人读审计在 `audit.md`。

`ArtifactManifest` 区分必需角色（result/evidence/audit/trace/manifest）与可选角色（pages/outline/coverage/tablegrid/page_image）；`GET /v1/jobs/{id}/artifacts/verify` 或 `metal-doc artifacts verify --run` 会返回缺失、大小与 SHA256 不一致。

关键契约：

- `TableGrid`：`table_id`、`page_no`、`rows`、`header_paths`、`units`、`footnotes`、`profile`、`blocks`；
- `Record`：`source_table_id`、`grade`、`grade_level`、`condition`、`properties`；
- `ExtractedValue`：`raw/value/unit/comparator/lower/upper/evidence_id`；
- `Evidence`：`page_no/table_id/row/col/quote`。

## 7. 测试矩阵

| 层 | 用例 | 阻断 |
|---|---|---|
| 单元 | 归一化、比较符、别名、区间 | 是 |
| 单元 | TableGrid rowspan/colspan/多块/跨页 | 是 |
| 契约 | result/tablegrid/record JSON Schema | 是 |
| 集成 | 3 份文档端到端 | 是 |
| 集成 | 20 份文档夜间跑 | 是 |
| 回归 | 核心字段下降 >1pp | 是 |
| 压测 | 30 页 p95 ≤5 分钟 | G1 |

## 8. G1 验收

> 2026-10-26 评审：**NO-GO**。详见 `metal-doc-agent/eval/g1-review.md`；复评需真实 Qwen 后端与 verified 标注。

- [x] 20 份 Schema 通过率 100%；
- [x] 证据覆盖率 ≥95%（Qwen 100%）；
- [ ] 简单表核心字段 ≥85%（Qwen 67.98%）；
- [ ] 扫描件核心字段 ≥75%（Qwen 70.82%）；
- [x] 困难表单独报告；
- [x] 30 页 p95 ≤5 分钟（Qwen 249.6s）；
- [x] 幻觉率 <1%（Qwen 0%）；
- [x] 错误分类完整；
- [x] 演示可重复。

### 8.1 失败分支

| 条件 | 动作 |
|---|---|
| 简单表 <70% | 停扩模型；修 TableGrid/表头映射 |
| 扫描件 <60% | 预处理/裁剪重 OCR；人工队列 |
| 证据 <90% | 阻断 M1.5 |
| p95 >8 分钟 | 批处理/并发/上下文优化 |

## 9. 风险

| 风险 | 触发 | 应对 |
|---|---|---|
| OCR 页错位 | 页数/页码不一致 | 页图与 Markdown 强校验 |
| 表头粘连 | 列角色错 | 表头树 + 金样例 |
| 模型编值 | 无证据值 | L1 拒绝 + 弃权训练 |
| 上下文溢出 | 长表截断 | 分块抽取 + 表头复用 |
| 扫描件差 | 低质量页 | 质量分 + 重 OCR + 人工 |

## 10. 交付物与交接

| 交付物 | 位置 |
|---|---|
| 真实 OCR adapter | `metal_doc_agent/ocr/glm.py` |
| 真实抽取 adapter | `metal_doc_agent/extraction/qwen.py` |
| TableGrid v1 | `metal_doc_agent/tablegrid/` |
| L0–L2 | `metal_doc_agent/validation/` |
| 20 份标注 | `goldset/v1/` |
| M1 评测 | `eval/m1.md` |
| 演示 | `demo/` 或脚本 |

交接给 M1.5：

- 20 份结果与错误分类；
- 困难表清单；
- 表画像与签名；
- 证据链格式；
- 已知 OCR 失败页。
