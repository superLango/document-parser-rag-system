# 新旧项目差异与审核-修复闭环分析

> 日期：2026-11-12
> 性质：只做分析，不做改造
> 结论先行：旧项目“大多数成功”主要来自**输入形态、兜底提取器数量、输出口径和修复闭环**，不是旧解析器本身更强；新项目审核没有触发修复，是因为**审核规则只覆盖单条记录、反馈需人工创建、修复只允许改配方 JSON，且 0 记录不会产生 finding**。

## 1. 结论

1. **旧项目的成功口径更宽**：旧系统输出 records + inspection_items + clauses + references + coverage，即使没有可解析的性能表，也会产出检验项目、条款或空 schema 行；“0 失败”不等于“字段都抽对了”。
2. **旧项目的输入更容易**：旧验证语料是 408 份 Markdown + 31 份 PDF 转 Markdown，表格已经是 HTML；新项目直接面对原始 PDF，必须先解决表格检测。两者不在同一起跑线。
3. **旧项目有更多确定性兜底**：旧 pipeline 对同一张表依次尝试 bound matrix、property matrix、grade-property matrix、property rows、grade-property tail、element matrix、hardness minmax、nonrecord 等多套提取器；新项目主要是一条 recipe binding 主循环 + 元素表兜底。
4. **旧项目有修复闭环**：L1 文档重解析 diff、L2 配置/配方修复、L3 代码修复提案（含策略、反硬编码、测试、可选自动合并）；新项目有 feedback/triage/repair/candidate/verify 的骨架，但没有和 review 自动衔接，且只修配方，不修解析代码。
5. **新项目审核对“0 记录”不敏感**：`run_rules` 是记录级循环，0 条记录时不会产生任何 finding；表级检查也要求 `table_id` 出现在记录计数里。因此 39 份 0 记录文档的 review 结果仍是 pass，自然不会触发任何修复。

## 2. 旧项目为什么“大多数都能成功解析”

### 2.1 输入形态不同：旧项目拿到的是“已结构化表格”

旧验证报告写得很清楚：

- 语料：`markdown/*.md` 408 份 + 项目内 PDF 31 份转 Markdown（35 份中 4 份扫描件跳过）。
- 旧 pipeline 的 `tablegrid` 从 Markdown/HTML 中解析 `<table>`，不负责“从 PDF 页面找表”。
- 新项目的 50 份标准是原始 PDF，AMS/ASME/ASTM 的表格没有框线，`page.find_tables()` 检不到；这是新项目 30 份 0 记录的直接原因。

即使把旧 `result.json` 的表格重建为 HTML 再喂给新系统（60 份对比），新系统也只覆盖了旧字段的约 49%（共同 1,442 / 旧 2,932）。这说明**输入不是唯一原因，但它是第一原因**。

### 2.2 旧项目对同一张表有多个提取器兜底

旧 `pipeline.py` 的提取顺序：

| 顺序 | 提取器 | 适用表 |
|---|---|---|
| 1 | `extractor.extract`（模型/规则） | 通用 |
| 2 | `extract_bound_matrix` | 已匹配配方、行列绑定明确的表 |
| 3 | `extract_property_matrix` | 性能矩阵 |
| 4 | `extract_grade_property_matrix` | 牌号行 + 性能列 |
| 5 | `extract_property_rows` | 属性-值竖表 |
| 6 | `extract_grade_property_tail` | 宽表尾部多性能列 |
| 7 | `extract_element_matrix` | 元素矩阵 |
| 8 | `extract_hardness_minmax` | 硬度 min/max |
| 9 | `extract_nonrecord` | 检验/非记录表 |

新项目 `builtin.py` 主要是：一条 recipe binding 主循环 + `_parse_element_table` + `_parse_chemical_columns`。当表头形态不在配方假设内时，旧系统还能换一种矩阵解析，新系统直接 `ROW_KEY_NOT_FOUND` / `MEASURE_COLUMN_MISSING`，然后 0 记录。

### 2.3 旧项目有硬表修复和领域词典

- 旧 `configs/table_repairs.json`：6 份文档、13 张表的定向修复，包含 `replace_rows` 7 次、`header_rows` 5 次、`delete_rows` 4 次、`trim_trailing` 4 次、`caption` 3 次等。
- 新 `services/ocr/data/table_repairs.json` 目前是空规则 `{"rules": []}`。
- 旧 `business_dictionary.hanson.json` 有 2,204 条领域词典；新项目已导入 2,203 条到业务词典，但未进入 `builtin.py` 的表格/字段绑定主循环（主要用于词典页面/术语）。
- 旧 `column_aliases.json` 的 family/property/role 关键词比新项目当前迁移的更全；旧还有 `coldstart` 冷启动配方、`routing` 队列和 `lifecycle` 版本管理。

### 2.4 旧项目有 L1/L2/L3 修复闭环

旧 `selfheal` 的能力：

| 层级 | 能力 | 作用 |
|---|---|---|
| L1 | 文档级重解析 + diff | 在隔离 sandbox 重跑，比较记录增删改，确认修复是否命中 |
| L2 | 配置/配方修复 | `column_alias.add`、`table_repair.add`、`recipe.binding_override` 等白名单算子 |
| L3 | 代码修复提案 | 只改规则代码，带 diff 策略、反硬编码门禁、回归测试、可选 `SELFHEAL_AUTO_MERGE` |

新项目有 `FeedbackService`、`TriageAgent`、`RepairAgent`、candidate/verify/promote 的骨架，但没有 L1 的独立重解析 diff，也没有 L3 代码修复；`RepairAgent` 的允许根只有 `/bindings`、`/signature`、`/rules`、`/templates`、`/compatibility`。

### 2.5 旧项目的“成功”包含大量非记录产物和占位值

旧验证报告的全量指标：

- 408 份 Markdown 全部完成，0 运行失败。
- 但 `no_inspection_table` 有 212 份，`low` 适用性 207 份。
- 非法牌号 103 条，“全部牌号”占位 887 条，取样数量缺失（检测行）949 条。
- 旧系统的 schema 行、检测项目行、条款、引用都算“产物”，所以“跑成功”不等于“性能表抽取成功”。

新项目只统计 records（化学/力学/硬度/检验规则等），0 记录就是 0 记录，因此看起来“新项目成功率低”，但两者成功率的分母不同。

## 3. 新旧路线逐项对比

| 维度 | 旧项目 | 新项目 |
|---|---|---|
| 输入 | Markdown/HTML（表格已结构化） | 原始 PDF（文本层/扫描件） |
| 表格检测 | 上游 Markdown 生成，pipeline 不做 PDF 表格检测 | `find_tables()` 线检测，无线表直接漏检 |
| 表格修复 | 6 文档/13 表定向修复 + 学习规则 | 空规则 |
| 提取器 | 9 种矩阵/非记录提取器 | 1 条 binding 主循环 + 2 个元素表兜底 |
| 配方 | 7 个配方 + coldstart + routing | 7 个配方 + 通道/版本，无 coldstart |
| 领域词典 | 2,204 条，参与 canonicalize/schema projection | 已导入 2,203 条，但解析链路未消费 |
| 输出口径 | records + items + clauses + references + coverage | 以 records 为主（4 类 profile） |
| 修复闭环 | L1 重解析 diff + L2 配置 + L3 代码提案 | feedback 骨架，手动触发，只修配方 JSON |
| 成功率口径 | 0 运行失败（含占位/非记录产物） | 有 records 才算成功 |
| 质量水分 | 非法牌号/占位/缺失较多 | 牌号/值原文命中高，但覆盖低 |

## 4. 为什么当前 agent 审核没有触发修复

### 4.1 审核规则是“记录级”的，0 记录直接跳过

`services/review/rules.py` 的 `run_rules`：

- 先遍历 `records`；没有记录时循环不执行。
- 表级检查只在 `table_id in table_counts` 时触发；0 记录时 `table_counts` 为空，因此不产生 finding。
- 唯一可能出现的“文档级问题”不存在，所以 39 份 0 记录文档 review 结果都是 `pass`。

### 4.2 模型审核是咨询性的，不产生反馈

`ReviewService.review`：

- 确定性规则 error → `fail`；模型 error → 只降级为 `warn`，不阻断。
- `warn` 不会进入 `REVIEW_FAILED`，也没有创建 feedback。
- 审核结果只是 `ReviewReport`，没有“质量分/覆盖率/0 记录”的文档级规则。

### 4.3 反馈需要人工创建，不是 review 自动触发

- `POST /v1/feedback` 由人工或前端创建。
- `POST /v1/feedback/{id}/process` 才运行 triage/repair/candidate/verify。
- orchestrator 的 review stage 没有调用 feedback API。

### 4.4 修复范围只到配方 JSON，且验证要求具体 measure

`RepairAgent` / `FeedbackService`：

- 允许 patch 根：`/bindings`、`/signature`、`/rules`、`/templates`、`/compatibility`。
- 非 `recipe` scope 一律 `needs_more_info`（转人工）。
- `_verify` 要求 `feedback.target.measure`；0 记录/表没检出的问题没有 measure，无法进入验证。
- 验证只重跑当前文档、只检查一个 measure，没有 50 份标准 + 金标回归。

### 4.5 所以答案是“应该触发，但现在没有触发条件”

不是 agent 不愿意修，而是：

1. 审核没有把“0 记录/漏表/覆盖率低”定义为问题；
2. 即使定义了，也没有自动创建 feedback；
3. 即使创建了，0 记录没有 measure，triage/repair 拿不到可验证目标；
4. 即使有目标，repair 也只能改配方，不能改表格检测/表头重建/OCR 代码；
5. 即使改了配方，验证也只有单文档单字段，没有回归门禁。

## 5. 正确的闭环应该是什么样（设计，不实施）

### 5.1 文档级质量门禁

在 review 前增加文档级规则，至少包括：

| 规则 | 触发条件 | 目标 |
|---|---|---|
| `DOC-NO-RECORDS` | records=0 且 tables>0 | 表存在但没有产出记录 |
| `DOC-NO-TABLES` | tables=0 且页数≥N | 表格检测失败 |
| `DOC-LOW-COVERAGE` | 有记录表数 / 可解析表数 < 阈值 | 覆盖不足 |
| `DOC-UNBOUND-COLUMNS` | MEASURE_COLUMN_MISSING 比例高 | 配方绑定不足 |
| `DOC-DUP-KEYS` | 同牌号同指标重复键 > 阈值 | 条件维度缺失 |
| `DOC-UNIT-MISSING` | 数值字段无单位比例 > 阈值 | 单位继承缺失 |

这些规则应产生 `error` 或 `warning`，并在 `ReviewReport.stats` 中带 `coverage`、`zero_record_tables`、`unbound_measures` 等字段。

### 5.2 review → feedback 自动创建

当文档级门禁命中时，自动创建 feedback：

- `category`: `missing_value` / `wrong_table` / `coverage`
- `target`: `document_id`、`table_id`、`recipe_id`，没有 measure 时允许 `target.type=table`
- `description`: 自动生成，例如“表 T3 存在但 0 记录”
- `source_quote`: 表标题/表头片段

### 5.3 triage 允许 table/document 级目标

当前 `TriageDecision` 的 repair_scope 支持 data/recipe/template/prompt/engine/display/none，但 verification 要求 measure。需要允许：

- `target.type=table`：验证“该表是否产出 ≥1 条记录”；
- `target.type=document`：验证“0 记录是否消除、覆盖率是否提升”；
- `target.measure` 可选；有 measure 时做字段级验证，没有时做表级/文档级验证。

### 5.4 修复分层：L1/L2/L3

| 层级 | 修复对象 | 是否自动 | 门禁 |
|---|---|---|---|
| L1 | 文档重解析 + diff | 自动 | 记录增删改 diff、无新增 error |
| L2 | 配方/别名/表修复 | 自动生成 candidate | 目标文档 + 回归集验证 |
| L3 | 解析代码（表格检测/表头/OCR） | 只生成提案 | diff 策略、反硬编码、测试、人工审批 |

新项目当前只有 L2 的一部分；L1 和 L3 需要补，但不能让 agent 直接改生产代码。

### 5.5 验证与晋升

- 目标文档：0 记录 → ≥1 记录；目标表：产出 ≥1 记录；目标字段：出现且值命中。
- 回归：50 份标准 + 30 份金标；有记录文档数、F1、静默错误、单位存在率不得回退。
- 晋升：candidate → shadow → stable；失败自动回滚，保留上一版本。

## 6. 优先级建议（仍不实施）

1. **P0：文档级质量规则 + 自动 feedback**。先让 0 记录/漏表变成“可见问题”，否则 agent 永远拿不到修复任务。
2. **P1：table/document 级 triage 与验证**。让 0 记录问题有可验证目标，而不是卡在 `TARGET_MEASURE_MISSING`。
3. **P2：L1 重解析 diff + 回归集验证**。防止修一个表、坏一片。
4. **P3：L3 代码修复提案**。参考旧 `selfheal/l3.py`、`codefix.py` 的白名单/反硬编码/测试/人工审批，不直接自动合并。
5. **P4：迁移旧 table_repairs 与更多别名**。旧 6 文档/13 表修复规则可逐条对照原文验证后迁入，不作为无条件规则。

## 7. 证据与相关文件

- 旧 pipeline：[pipeline.py](../../../legacy/metal-doc-agent/metal_doc_agent/pipeline.py)
- 旧 matrix 提取器：[matrix.py](../../../legacy/metal-doc-agent/metal_doc_agent/extraction/matrix.py)
- 旧 selfheal：[l1.py](../../../legacy/metal-doc-agent/metal_doc_agent/selfheal/l1.py)、[l2.py](../../../legacy/metal-doc-agent/metal_doc_agent/selfheal/l2.py)、[l3.py](../../../legacy/metal-doc-agent/metal_doc_agent/selfheal/l3.py)、[codefix.py](../../../legacy/metal-doc-agent/metal_doc_agent/selfheal/codefix.py)
- 旧全量验证：[extraction-validation-full-2026-11-06.md](../../../legacy/docs/extraction-validation-full-2026-11-06.md)
- 新审核规则：[rules.py](../../services/review/rules.py)
- 新反馈闭环：[service.py](../../services/orchestration/feedback/service.py)
- 新修复 Agent：[repair.py](../../services/agent/agents/repair.py)
- 新旧对比：[closeout-effect-comparison.md](closeout-effect-comparison.md)
- 50 份标准核对：[closeout-standards-audit.md](closeout-standards-audit.md)
