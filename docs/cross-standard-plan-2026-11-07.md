# 跨标准补全开发方案

- 版本：v1.1（P0–P3 已实施）
- 日期：2026-11-07
- 现状代码：`metal_doc_agent/cross_standard.py`、`standards.py`、`references.py`、`relevance.py`、`items/discover.py`
- 目标版本：当前生产 r7-34（engine/worker r7-32、web r7-31）

## 1. 目标与非目标

### 目标

当当前标准只给出“按某标准规定执行”，而没有给出具体参数时，系统能够：

1. 识别缺失参数（已有基础能力）；
2. 解析被引标准的正确版本；
3. 在本地正文中定位对应条款/表格；
4. 抽取缺失字段的值，并带来源（标准、版本、条款/表、页码、原文）；
5. 合并进当前文档的结果行，且不覆盖本文件已有的值；
6. 在 API/UI 中展示任务、来源、冲突和人工确认入口。

### 非目标

- 不自动下载外网标准；
- 不做多跳展开（A 引 B、B 引 C 的递归）；
- 不改写本文件已有的标准要求；
- 不处理英文标准的语义翻译（单独轨道）；
- 不为了让结果“看起来完整”而猜测数值。

## 2. 现状与缺口

### 已有

| 能力 | 位置 | 现状 |
| --- | --- | --- |
| 引用图 | `references.py` | 规范性引用章节 + 正文引用，输出去重引用边 |
| 版本解析 | `standards.py` | 注日期精确匹配、不注日期取唯一现行、旧版找替代版本 |
| 相关性/预算 | `relevance.py` | schema/method/informative/unknown 分类；1-hop 预算 8 份/30 页（仅计划） |
| 按需任务 | `cross_standard.py` | 仅识别“按 XX 规定的 YY 进行 ZZ”句式；输出任务及来源定位 |
| 项目清单 | `items/discover.py` | 任务转成 `source="reference"` 的项目条目 |
| 离线工具 | `tools/cross_standard_pilot.py` | 可把任务落盘为 JSON/Markdown，但不在生产流水线中 |

### 缺口

1. **任务不落盘**：生产 pipeline 只记录数量，结果中看不到任务和缺口。
2. **不读取被引正文**：`resolved_source_file` 只用于标记来源，没有展开动作。
3. **方法标准未回填**：`detect_tasks` 没有填 `method_standard`，引用项目没有方法。
4. **句式覆盖窄**：只覆盖“按 XX 规定的 YY 进行 ZZ”。
5. **无法合并**：没有“外部值 → 当前行”的合并规则和 provenance。
6. **预算未执行**：`expand` 标记没有消费者。
7. **无 API/UI**：任务和缺口不可见，无法人工确认或忽略。

## 3. 总体设计

采用“**任务 → 解析 → 展开 → 合并 → 复核**”五段式，所有阶段可单独重跑、可审计。

```
当前文档
  └─ detect_tasks            (已有，扩展句式)
       └─ resolve            (注册表 + 语料正文 + mentions)
            ├─ resolved      → expand
            ├─ candidate     → 标记待确认（不自动展开）
            ├─ needs_source  → gap，等待补正文
            └─ not_found     → gap
                 └─ expand   (定位条款/表 → 抽取字段 → 证据)
                      └─ merge (只填空值/表引用，不覆盖)
                           └─ review (自动接受 / 人工确认 / 忽略)
```

### 3.1 任务模型（扩展 `CrossStandardTask`）

新增字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `status` | enum | `needed / resolved / candidate / needs_source / not_found / expanded / ignored / failed` |
| `resolution` | object | `{standard_no, edition, doc_id, source_file, basis, verified}` |
| `expansion` | object | `{job_id, clause_id, table_id, page_no, extracted[], confidence}` |
| `merge` | object | `{target_row_key, target_field, applied, conflict, before, after}` |
| `provenance` | array | `{source_file, page_no, clause_id, table_id, quote}` |
| `attempts` | int | 展开次数，用于重试与审计 |
| `error` | string | 失败原因 |

任务 ID 保持现有 `xstd-<sha1>`，保证幂等。

### 3.2 版本解析（强化 `standards.py`）

1. 用 `configs/standards.json` 作为唯一版本事实源；
2. 把 `data/standards_library/catalog.json` 中 53 份有标准号的正文登记为候选记录（脚本生成，人工确认）；
3. 规则保持：
   - 注日期 → 精确版本；
   - 不注日期 → 唯一现行；
   - 旧版 → `supersedes` 链；
   - 多现行 → `conflict`，不展开；
4. `candidate`（只有 mentions）不自动展开，必须人工确认或补正文。

### 3.3 定位器（新增 `cross_standard/locator.py`）

输入：任务（检验项目、缺失字段、条款号、原文）+ 被引标准的解析产物。

定位顺序：

1. **条款号命中**：任务 `clause_id` 在被引标准 `clauses.jsonl` 中存在 → 直接取该条款正文；
2. **字段关键词**：在条款正文中找 `missing_field`（如“弯曲半径”）±30 字窗口；
3. **表号命中**：原文含“表X” → 按 `caption` 匹配 `tablegrid`；
4. **表头/项目匹配**：按检验项目/字段关键词匹配表头路径，再用 `column_bindings` 找列；
5. **LLM 兜底**：只允许在给定条款/表格文本内选择字段和值，输出 JSON；置信度 ≤0.6，必须人工确认。

输出：

```json
{
  "field": "弯曲半径",
  "value": "1.5",
  "unit": "mm",
  "source_text": "……弯曲半径按表2选取……",
  "clause_id": "5.3",
  "table_id": "T4",
  "page_no": 12,
  "confidence": 1.0
}
```

### 3.4 合并器（新增 `cross_standard/merge.py`）

合并规则（按优先级）：

1. 当前行 `标准要求` 为空 → 填入外部值；
2. 当前行 `标准要求` 是表引用（如“应符合表1的规定”）→ 用外部值替换引用文本，并保留 `（依据 GB/T xxx 表Y）` 到 provenance，不写入正文；
3. 当前行已有具体值 → **不覆盖**，记录 `conflict`，进入人工复核；
4. 当前行 `试验方法` 为空 → 用任务/被引标准的方法标准回填；
5. 取样数量/说明缺省 → 仅在字段明确对应时回填。

合并只作用于 `ItemInventoryEntry` 对应的目标行；目标行通过 `record_id + 项目名称` 或 `item_id + property` 定位。

### 3.5 复核策略

| 场景 | 默认动作 |
| --- | --- |
| 精确条款/表 + 字段命中（confidence=1.0） | 自动合并，标记 `expanded` |
| 关键词命中（0.8） | 自动合并，进入 `review` 列表 |
| LLM 兜底（≤0.6） | 只生成候选，不合并，需人工确认 |
| `candidate`（无正文） | 不展开，提示补正文 |
| 冲突 | 不覆盖，标记 `conflict` |

### 3.6 持久化与 API

**产物**（每个 job）：

- `cross_standard_tasks.json`
- `cross_standard_expansion.json`
- `cross_standard_merge.json`
- `cross_standard_report.md`

**API**：

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| GET | `/v1/documents/{id}/cross-standard/tasks` | 任务列表（状态、缺口、来源） |
| POST | `/v1/documents/{id}/cross-standard/tasks/{task_id}/expand` | 手动触发展开 |
| POST | `/v1/documents/{id}/cross-standard/tasks/{task_id}/ignore` | 忽略任务 |
| POST | `/v1/documents/{id}/cross-standard/tasks/{task_id}/confirm` | 确认/修改外部值 |
| GET | `/v1/documents/{id}/cross-standard/report` | 任务报告 |

**前端**：结果页增加“跨标准补全”页签：任务表格（项目、缺失字段、要求标准、状态、来源、缺口、操作），展开后显示来源条款/表和原文，支持确认/修改/忽略。

## 4. 实施阶段

### P0：任务可见（先解决“看不见”）

1. pipeline 写出 `cross_standard_tasks.json`；
2. API 增加任务列表；
3. 前端增加任务列表页签（只读）；
4. 任务写入 trace/metrics。

验收：任选 5 份含“按 XX 规定”的文档，任务数量、状态、缺口与离线 `cross_standard_pilot.py` 一致。

### P1：版本与来源加固

1. 从 catalog 生成候选注册表，人工确认后合并进 `configs/standards.json`；
2. 补 `method_standard`（从被引标准的项目/条款中回填）；
3. 处理 `candidate / needs_source / conflict` 的 UI 提示；
4. 预算真正生效：`max_documents=8`、`max_pages=30`、`page_budget_used`。

验收：`resolved / candidate / needs_source / not_found` 四类状态都有样本；版本冲突不展开。

### P2：规则展开（条款/表格）

1. 新增 locator：条款号 → 条款正文 → 字段窗口；
2. 表号 → caption → 表头/列绑定 → 行匹配；
3. 抽取值（数值/范围/单位）并生成 provenance；
4. 只处理 `resolved` 任务。

验收：GB/T 3880.2 弯曲半径、QJ502B 低倍表4、DFHM 表1 三个样例能定位到正确条款/表；人工核对值正确。

### P3：合并与复核

1. 实现 merge 规则（空值/表引用可填，已有值不覆盖）；
2. 冲突列表与人工确认；
3. 合并结果进入 schema 投影，保持原有字段不变；
4. provenance 在 API/UI 可见。

验收：合并后当前行标准要求非空，且来源可追溯；冲突不被静默覆盖。

### P4：句式扩展

新增识别：

- “应符合 GB/T xxx 的规定”（无“进行”动词）；
- “见 GB/T xxx 第 X 章 / 表 X”；
- “按表 X 选取/确定”；
- 复合引用“除按 GB/T A 外，还应符合 GB/T B”；
- 可选要求“根据需方要求增加……”。

验收：测试集召回率提升，且不把普通方法引用误判为缺失参数。

### P5：评估与回归

1. 建立 10-20 份跨标准测试集（含可解析/不可解析/冲突）；
2. 统计任务召回、定位准确率、值准确率、合并冲突率；
3. 重跑 50 份抽样审计，确认不引入新问题；
4. 记录缓存命中率与耗时。

## 5. 数据结构示例

```json
{
  "task_id": "xstd-1a2b3c4d5e",
  "doc_id": "current-doc",
  "inspection_item": "弯曲性能",
  "missing_fields": ["弯曲半径"],
  "requirement_standard": "GB/T 3880.2",
  "requirement_edition": "2012",
  "clause_id": "3.6",
  "page_no": 18,
  "quote": "按GB/T3880.2规定的弯曲半径进行弯曲试验",
  "status": "expanded",
  "resolution": {
    "standard_no": "GB/T 3880.2",
    "edition": "2012",
    "doc_id": "gbt3880_2_2012",
    "source_file": "markdown/xxx.md",
    "basis": "dated",
    "verified": true
  },
  "expansion": {
    "job_id": "ref-job-001",
    "clause_id": "5.3",
    "table_id": "T2",
    "page_no": 12,
    "extracted": [
      {"field": "弯曲半径", "value": "1.5", "unit": "mm", "confidence": 1.0}
    ],
    "confidence": 1.0
  },
  "merge": {
    "target_row_key": "弯曲性能/弯曲半径",
    "target_field": "标准要求",
    "applied": true,
    "conflict": false,
    "before": "",
    "after": "1.5mm"
  },
  "provenance": [
    {
      "source_file": "markdown/xxx.md",
      "page_no": 12,
      "clause_id": "5.3",
      "table_id": "T2",
      "quote": "……弯曲半径按表2选取……"
    }
  ]
}
```

## 6. 风险与对策

| 风险 | 对策 |
| --- | --- |
| 被引标准是扫描件/图片，OCR 成本高 | 只在任务为 `resolved` 时展开；按 sha256 缓存解析产物；预算限 8 份/30 页 |
| 版本不唯一/冲突 | `conflict` 不展开，UI 提示人工选择 |
| 条款号不一致（如引用标准内部编号变化） | 条款号优先，字段关键词兜底，LLM 只做候选 |
| LLM 编造值 | LLM 只允许在给定文本内选择；输出必须带 quote；≤0.6 置信度不自动合并 |
| 覆盖本文件已有值 | merge 只填空/表引用；冲突记录不覆盖 |
| 展开拖慢主流程 | 展开异步化；主解析先出结果，任务后台补全 |
| 标准版权/合规 | 仅使用本地已入库正文；不自动下载 |

## 7. 验收标准

1. 5 份样例文档的任务全部可见，状态与来源正确；
2. 3 个已知缺失参数（弯曲半径、低倍表4、化学成分表1）能定位到正确条款/表，值人工核对正确；
3. 合并只发生在空值或表引用行，已有值 0 覆盖；
4. 冲突、候选、缺正文三类状态在 API/UI 可见且可操作；
5. 50 份抽样复测不新增“空标准要求/表格引用未展开”问题；
6. 单文档跨标准展开的额外耗时不超过主解析的 50%（缓存命中时接近 0）。

## 9. 与 r7-30 全量复测的衔接

50 份抽样全量复测（`data/audit-sample50-2026-11-07/regression_r7-30_report.md`）结果：问题总数 677 → 288（-57.5%），0 失败；强度/塑性可疑值、占位值已清零。剩余问题中与本方案直接相关的是：

| 残留问题 | 数量 | 与跨标准的关系 |
| --- | ---: | --- |
| 表格引用未展开 | 2 | QJ502B 低倍“按表4”、DFHM“应符合表1”；正是“定位源表并展开”的首批样例 |
| 空标准要求 | 81 | 其中一部分是“引用外部标准但未取值”，可由跨标准展开补齐 |
| 试验方法为空 | 117 | 其中方法标准引用可由任务 `method_standard` 回填，但定性项目仍应允许为空 |

因此本方案的首批验收样例直接采用：

1. `33_QJ502B-2014.pdf` 低倍“按表4中规定检查低倍组织”；
2. `13_DFHM-QCD-0706-000893采购规范模板+B.pdf` “化学成分应符合表1的规定”；
3. GB/T 3880.2 弯曲半径样例（单测已有）。

同时设置质量门槛：跨标准展开不得重新引入强度/塑性可疑值或占位值；所有外部值必须带 provenance，冲突不覆盖。

## 11. 实施状态（2026-11-07）

P0–P5 已按本方案实施并部署到 `r7-40`（engine/worker `r7-40`、platform-api `r7-34`、web `r7-31`）。

| 阶段 | 状态 | 落地内容 |
| --- | --- | --- |
| P0 任务可见 | 完成 | `cross_standard_tasks.json` 落盘；`GET /v1/documents/{id}/cross-standard/tasks`；结果页“跨标准补全”卡片 |
| P1 版本/来源 | 完成（method_standard 待补） | 任务展示 `resolved_source_file / resolution_basis / gap`；展开预算 8 份/30 页；`candidate/needs_source/not_found` 状态可见 |
| P2 规则展开 | 完成 | `cross_standard_expand.py`：条款号→条款正文→字段窗口；表号→caption/表格 profile→列；写 `cross_standard_expansion.json` |
| P3 合并/复核 | 完成 | `cross_standard_merge.json` + `cross_standard_overrides.json`；精确命中自动填空值/表引用；确认/忽略接口；provenance 单独保存 |
| P4 句式扩展 | 完成 | `detect_tasks` 支持四类句式 + 参数名词白名单（见下） |
| P5 评估与回归 | 完成 | 20 份人工标注 + 50 份审计抽样；召回/精度、定位/取值、合并冲突、性能（见下） |

新增接口：

- `GET /v1/documents/{id}/cross-standard/tasks`
- `POST /v1/documents/{id}/cross-standard/tasks/{task_id}/expand`
- `POST /v1/documents/{id}/cross-standard/tasks/{task_id}/confirm`
- `POST /v1/documents/{id}/cross-standard/tasks/{task_id}/ignore`

验证：

- 单元测试：`tests/test_cross_standard.py` 覆盖条款定位、字段抽取、缺正文降级；`tests/test_schema_projection.py` 覆盖无图题表格的 profile 约束回退。
- API 验证：在 DFHM 文档上注入测试任务，确认后化学成分行变为确认值，忽略后状态为 `ignored`，验证后清理。
- 引擎测试 453 passed（仅 2 个既有非功能失败），平台 API 测试 63 passed。

### P4 句式扩展（r7-35）

`detect_tasks` 现覆盖四类句式，且仅在命中“缺失参数”时建任务：

1. `按照? <std> [标准]?[之的]?规定[的]? <field> <进行|执行|检验|…>`；
2. 同上但无动词（`按 GB/T 3880.2 规定的弯曲半径`）；
3. `<field> 应符合/满足 <std> [中…] [的]?规定/要求`（如“成品化学成分允许偏差应符合 GB/T 222 的规定”）；
4. `<field> 应按 <std> [中…]? [的]?[规定]? [进行]? <verb>`（如“低倍缺陷应按 GJB 9443 进行检验”）。

关键约束：

- 标准号 token 允许机构与编号间有空格（`GB/T 3880.2`），并覆盖 `GJB/Z、HB/Z、AMS-STD、Q/企业代号、JX/MAS/MFS`；
- 字段必须命中参数名词后缀白名单（半径、允许偏差、级别、晶粒度、组织、缺陷、余量、公差、温度、方向、数量、含量等）；纯方法引用（“低倍试样制备按 GB/T 226 的规定进行”“超声检测按 GJB 1580A 的规定进行”）不建任务；
- 字段清洗会去掉产品前缀（锻件/成品/棒材…）、填充词（其/该/所有/重新/逐根…）与动词前缀，并剔除“项目/要求/结果”等泛化词；
- 无 `inspection_item` 时从字段反推（化学成分、低倍组织、晶粒度、非金属夹杂物、表面质量等），便于与投影行匹配。

实测：

- 语料 408 份 markdown：98 份命中、216 个任务；字段以“化学成分允许偏差(44)/加工余量及公差(20)/允许偏差(15)/晶粒度(13)/非金属夹杂物(10)/低倍缺陷(10)”为主；
- 311 个历史 job 的 `pages.json` 离线重扫（0 失败）：80 个 job 命中 185 个任务，状态 `candidate 126 / not_found 59`；
- 单元测试 `tests/test_cross_standard.py` 14 passed（新增 5 个 P4 正/负例）。

**当前限制**：

1. 历史 job 与语料中的被引标准多为方法标准（GB/T 222、GB/T 6394、GB/T 702 等），本地语料只有 53 份“正文”且不含这些标准，因此任务停在 `candidate`（“语料中 N 份文件引用，无正文”）或 `not_found`，`expand_tasks` 不会执行；要产出补全值，需要把被引方法标准正文纳入 `markdown/`。
2. 容器内的 `data/standards_library/catalog.json` 原先未挂载，导致 `candidate` 退化为 `not_found`；r7-35 已把 `metal-doc-agent/data/standards_library` 只读挂载到 engine-api/两个 worker。
3. 跨标准任务的 `method_standard` 尚未从来源条款回填，当前仍依赖文档级方法索引。

### P5 评估与回归（r7-40）

测试集：

- 20 份 job 文档（生产 `pages.json`，按文件名去重后的 96 份中抽取：16 份有任务 + 4 份无任务）；
- 50 份 r7-30 审计抽样（`data/audit-sample50-2026-11-07/regression_documents_r7-30.json`）。

| 指标 | 结果 | 说明 |
| --- | --- | --- |
| 任务召回 | 44 / 44 = 100% | 20 份文档人工标注应建任务；含“断面收缩率应按…规定”“表面质量也可符合/执行”“成份允许偏差按…表3规定”等句式 |
| 任务精度 | 44 / 44 = 100% | 修正前 3 个误报：`A 法`/`评级图` 方法引用、“规定的方法计算”；已按方法提示词过滤 |
| 任务状态 | candidate 23 / not_found 23 / resolved 0 | 96 份去重文档、46 个任务；被引方法标准无本地正文 |
| 定位准确率 | 生产 1 例：0 / 1 | `测试项目 → Q/S 10-0537`（字段未出现在来源正文，正确不合并） |
| 取值准确率 | 受控 1 / 1 | 真实来源正文 Q/S 10-0537：`取样数量` → 表 T5、p6、值 `1`、置信度 0.9 |
| 合并冲突率 | 0 / 0 | 生产 0 条 merge；受控 1 条合并，无冲突 |
| 50 份回归 | 12 份 / 19 个任务 / 0 展开 / 0 合并 | 无跨标准值写入 → 投影结果不变，未引入新问题 |
| 检测耗时 | 4.52 s / 96 份 = 47.1 ms/份 | 纯规则，无模型调用 |
| 展开耗时 | 0.039 s / 3 个任务 | 0 份可展开，缓存命中率不适用 |

本轮顺带修复：

- 注册表已解析但 `source_file` 为空时，回退使用语料正文，避免“已解析却无法展开”；
- `成份` → `成分` 归一；`表 4` 这类表号不再被当作要求值（避免 1.0 置信度误合并）；
- OCR 重复行（同页、同标准、同字段、去空格后同引文）合并，减少重复任务；
- `inspection_item` 过滤无语义标题（纯编号、整句），并用字段反推项目名。

**仍未闭环**：生产语料没有被引方法标准（GB/T 222、GB/T 6394、GB/T 702 等）的正文，因此 `resolved = 0`，展开/合并只能在受控样例与单元测试中验证；把方法标准正文纳入 `markdown/` 后即可直接产出补全值。

## 12. 需要确认的决策点

1. **自动合并边界**：精确命中是否直接写入结果，还是全部进入 review？（建议：精确命中自动写入，关键词/LLM 进 review）
2. **来源展示**：外部值是否在 `标准要求` 文本中追加“（依据 GB/T xxx）”，还是只在 API/UI 展示 provenance？（建议：正文保持干净，provenance 单独展示）
3. **注册表维护**：是否允许从 catalog 自动生成候选记录，由人工批量确认？（建议：允许生成候选，不自动改为 current）
4. **展开时机**：解析完成即后台展开，还是用户点击“补全”再展开？（建议：默认后台展开 resolved 任务，candidate 保持手动）
5. **多跳**：是否允许 A→B→C 两跳？（建议：本期只做 1 跳）
