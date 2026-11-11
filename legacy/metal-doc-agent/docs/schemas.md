# Schema v0（M0-02）

> 状态：冻结候选（v0.1.0），等待业务/领域签字。
> 代码契约：`metal_doc_agent/contracts.py`；JSON Schema：`schemas/v0/`（`metal-doc schema export` 生成）。
> 黄金集：`goldset/v0/`；标注规范：`docs/annotation.md`。

## 1. 范围与边界（M0-01）

首期支持 4 类文档、5 类表：

| 维度 | v0 范围 |
|---|---|
| 文档类型 | GB/T、GJB、企业规范、技术/采购协议、分类标准（manifest 实际覆盖 5 类） |
| 表类型 | 化学成分、力学性能、检验规则、牌号/状态分类、尺寸偏差 |
| 字段来源 | 表格 + 条款段落 |
| 输出 | `result.json`（结构化）+ `evidence.jsonl`（证据）+ `audit.md`（审核） |
| 证据 | 每个抽取值必须有页码、表/条款定位和原文引用 |
| 缺失值 | 显式 `status` 或 `not_applicable`，不猜值 |

v0 明确**不做**：

- 尺寸/公差表的类型化抽取（v0 只保留 `TableGrid`，M1.5 再做 `DimensionItem`）；
- 跨标准引用闭包与版本合并（`ReferenceGraph` 契约已定义，M1.5 实现）；
- 全条款自动抽取（规则版 `ClauseRecord` 已在 M1.7 落地：方法/方向/位置/数量/温度/判定；复杂条款仍待 M3）；
- 复核 UI、生产队列、对象存储（M3/M4/M5）。

边界原则：v0 保证“文档可映射到契约、黄金集可评分”，不保证“所有字段都自动抽到”。

## 2. 顶层结果

```json
{
  "schema_version": "0.1.0",
  "producer_version": "0.1.0",
  "document": { "doc_id": "...", "standard_no": "...", "page_count": 10 },
  "profile": { "doc_type": "enterprise", "product_form": "锻件", "table_profiles": ["..."] },
  "tables": [ { "table_id": "T2", "profile": "mechanical_properties" } ],
  "records": [ { "record_id": "rec-...", "grade": "2A14", "condition": "...", "properties": {} } ],
  "inspection_items": [],
  "classification_items": [],
  "clauses": [],
  "references": null,
  "coverage": { "template": "enterprise", "items": [] },
  "quality": { "status": "review", "issues": [], "stats": {} },
  "artifacts": { "result": "result.json", "evidence": "evidence.jsonl" }
}
```

顶层 artifact 统一带 `schema_version`、`producer_version`；`created_at` 暂由 `manifest.json` / `trace.json` 记录，M1-02 引入对象存储时进入 artifact header。

## 3. 实体定义

| 实体 | 关键字段 | 说明 |
|---|---|---|
| `DocumentMeta` | `doc_id`、`standard_no`、`title`、`version`、`page_count`、`sha256` | 文档身份；`doc_id` 全局唯一 |
| `DocumentProfile` | `doc_type`、`material_family`、`product_form`、`table_profiles`、`coverage_template` | 文档画像，用于路由与覆盖模板 |
| `Page` | `page_no`、`markdown`、`image_path` | 页级 OCR 结果；页码从 1 开始 |
| `TableGrid` | `table_id`、`page_no`、`caption`、`rows`、`header_paths`、`merges`、`units`、`footnotes`、`profile`、`orientation`、`blocks` | 展开 rowspan/colspan 后的网格；多块表用 `blocks` |
| `OutlineGraph` / `OutlineNode` | `doc_id`、`nodes[]`；节点含 `node_id`、`kind`、`title`、`clause_id`、`page_no`、`level`、`parent_id`、`normative` | 文档大纲；`clause_id` 支持 `7.4` 与 `B.2.3` 形式 |
| `Evidence` | `evidence_id`、`page_no`、`table_id`、`row`、`col`、`quote`、`bbox` | 单元格级证据；`evidence_id` 形如 `ev:{doc}:{table}:r{row}:c{col}` |
| `Record` | `record_id`、`source_table_id`、`grade`、`grade_level`、`condition`、`facets`、`properties` | 一条“牌号/级别 × 条件”的取值集合 |
| `ClauseRecord` | `clause_id`、`kind`、`fields`、`applies_to`、`evidence`、`status` | 条款级字段（方法/方向/位置/数量/温度/判定） |
| `InspectionItem` | `item`、`quantities`、`sample_location`、`requirement_clause`、`method_clause`、`method_standard` | 检验项目矩阵的一行 |
| `ClassificationItem` | `grade`、`old_grade`、`state`、`old_state`、`meaning` | 牌号/状态分类表的一行 |
| `CoveragePlan` | `template`、`items` | 必填字段的 found/missing/ambiguous/not_applicable |
| `AuditReport` | `status`、`issues`、`stats` | L0–L3.5 审核结果 |
| `ReferenceGraph` | `references`、`gaps`、`budget` | 跨标准引用边；每条边含 `standard_no`、`edition`、`page_no`、`clause_id`、`resolved`、`resolution_basis`、`status`、`superseded_by`、`relevance`、`expand`；`gaps` 记录未解析引用及原因；`budget` 记录 ≤8 份/≤30 页的展开预算 |
| `CrossStandardTask` | `task_id`、`inspection_item`、`missing_fields`、`requirement_standard`、`method_standard`、`clause_id`、`page_no`、`optional`、`status`、`resolved_source_file`、`gap` | 缺口驱动的跨标准补全任务；仅当当前文件只给方法/标准指针、缺少具体参数时生成；`status` 为 `needed/resolved/candidate/needs_source/not_found/ignored`；`resolved_source_file` 指向语料中命中正文的文件（`resolution_basis=corpus-body`），版本可解析但语料只有引用、没有正文时记 `needs_source` |
| `Recipe` | `recipe_id`、`version`、`status`、`profile`、`signature`、`bindings`、`rules`、`coverage_template`、`business_dictionary` | M1.6 声明式表型配方；签名 + 列绑定 + 规则 + 覆盖模板 + 业务词典绑定；不按文件写代码 |
| `ColumnBinding` | `column`、`header_path`、`item_family`、`item_raw`、`property`、`role`、`unit`、`facets`、`confidence`、`status`、`reason` | 列语义绑定；`role` 为 `row_key/row_index/condition/measure/method/remark/unknown`；`facets` 记录温度/冲击类型/硬度标尺等维度 |
| `ItemGroup` | `group_id`、`item_family`、`item_raw`、`columns`、`facets`、`status` | 列组式项目分组（拉伸/冲击/持久/硬度等） |
| `ColumnBindingResult` | `table_id`、`recipe_id`、`match_status`、`bindings`、`item_groups`、`conflicts`、`ambiguous`、`unmapped_columns` | 单表列绑定结果；冲突/歧义/未映射显式记录 |
| `ItemInventoryEntry` | `item_raw`、`item_canonical`、`item_family`、`facets`、`properties`、`method_standard`、`source`、`clause_id`、`page_no`、`table_id`、`evidence`、`status` | 单个检验项目；`source` 为 `inspection_table/property_table/clause/reference/manual`，`status` 为 `confirmed/probable/new/ambiguous/not_applicable` |
| `ItemInventory` | `doc_id`、`items`、`unknown_candidates`、`not_applicable`、`coverage`、`recipe_ids` | 文档级项目清单；覆盖统计含 measure 列覆盖率、未映射列、未知候选 |
| `TableClauseLink` | `table_id`、`clause_id`、`clause_title`、`page_no`、`basis`、`confidence`、`evidence` | 表-条款链接；`basis` 为 `explicit/caption/section/nearest/continuation/none` |
| `TableLinkResult` | `doc_id`、`links[]`、`orphans[]`、`coverage` | 表-条款链接结果；`coverage` 含 `tables/linked/explicit/nearest/unlinked/link_rate` |
| `CoverageAudit` | `doc_id`、`status`、`items[]`、`gaps[]`、`stats` | 项目驱动覆盖审计；检查 measure 列、条款提及、表链接、孤儿行、未覆盖属性表 |
| `BusinessDictionary` / `BusinessDictionaryEntry` | `version`、`source`、`entries[]`；条目含 `business_code`、`business_name`、`type`、`family`、`facets`、`aliases`、`standard_no`、`status` | 业务主数据快照；JSON/API/DB 三源适配 |
| `CanonicalMatch` | `raw`、`canonical_id`、`canonical_name`、`match_type`、`score`、`dictionary_version`、`evidence`、`status` | 项目/方法匹配结果；`match_type` 为 exact/alias/granularity/semantic/edit_distance/new/ambiguous |
| `NewTerm` / `NewTermStore` | `type`、`raw`、`family`、`facets`、`suggested_code`、`reason`、`frequency`、`status`、`dictionary_version` | 新项目/新方法候选；pending→active/rejected，支持回流本地词典 |
| `AlignmentResult` | `doc_id`、`dictionary_version`、`item_matches[]`、`method_matches[]`、`new_terms[]`、`summary` | 文档级业务对齐结果；`ItemInventoryEntry` 同步写入 `business_code/method_code/match_type/dictionary_version` |
| `ExtractionPlan` | `template`、`fields` | 抽取计划（字段 → 来源 → 表型） |
| `ArtifactManifest` | `job_id`、`doc_id`、`artifacts[]` | artifact 清单；每项含 `path/role/content_type/size/sha256/required` |
| `JobState` | `job_id`、`status`、`stage`、`progress`、`summary`、`artifact_manifest` | 任务状态；`queued/running/succeeded/failed/review`，终态不可重跑成功任务 |

## 4. 值模型

`ExtractedValue` 的字段：

| 字段 | 含义 | 规则 |
|---|---|---|
| `raw` | 原文片段 | 保留 OCR 原文（含空格、`≤`、`~`），不得改写 |
| `value` | 规范数值 | `eq/min/max` 使用；文本值必须为 `null` |
| `lower`/`upper` | 区间 | `comparator=range` 必填 |
| `text` | 文本值 | `comparator=text` 必填 |
| `unit` | 单位 | 取表头/条款单位；无量纲百分比用 `%` |
| `comparator` | 判定方向 | 见下表 |
| `condition` | 该值局部条件 | 例如 `≤40mm`、`室温` |
| `evidence_id` | 证据指针 | 非空；不可指到不存在的 evidence |

`comparator` 语义：

| 值 | 含义 | 例 |
|---|---|---|
| `eq` | 精确等于 | `120` |
| `min` | 不小于（下限） | 表头“不小于”、`≥` |
| `max` | 不大于（上限） | 表头“不大于”、`≤`、`余量`以外的上限 |
| `range` | 闭区间 | `0.015~0.060` |
| `text` | 文本/定性 | `余量`、`提供实测数据` |
| `na` | 明确不适用 | `-` / `不要求` |

关键规则：`comparator` 描述**要求方向**，不是书写形式。表头写“不小于”时，即使单元格只写 `430`，也必须是 `min`。这正是黄金集能暴露“值对但语义错”的原因。

## 5. 规范字段字典

### 5.1 力学/物理性能

| 规范名 | 别名（清洗后） | 单位 |
|---|---|---|
| `Rm` | `σb`、`σb/MPa`、`抗拉强度`、`抗拉` | MPa |
| `Rp0.2` | `σ0.2`、`σ0.2/MPa`、`屈服强度`、`屈服`、`规定塑性延伸强度` | MPa |
| `ReH` | `上屈服强度`、`ReH` | MPa |
| `A` | `δs`、`δ5`、`断后伸长率`、`伸长率` | % |
| `A50mm` | `A50mm`、`定标距断后伸长率` | % |
| `Z` | `ψ`、`断面收缩率` | % |
| `KV2` | `KU1`、`KU2`、`KU5`、`冲击`、`冲击吸收能量` | J |
| `HB` | `HBW`、`布氏硬度` | HBW |
| `HRC` | 洛氏硬度 C 标尺 | HRC |
| `HRB` | 洛氏硬度 B 标尺 | HRB |
| `HV` | 维氏硬度 | HV |
| `E` | `弹性模量` | GPa |
| `KIC` | `断裂韧度`、`KIC` | MPa·m^1/2 |
| `H_liquid` | 液态氢含量 | mL/100gAl |
| `H_solid` | 固态氢含量 | μg/g |

> 评测时 `KU1/KU2/KU5 → KV2`、`HBW → HB` 会先做别名归一，再按规范名比对。

### 5.2 化学元素

`ELEMENTS` 白名单（`tablegrid/normalize.py`）：C、Si、Mn、P、S、Cr、Ni、Mo、Al、Ti、Fe、Cu、Nb、Ta、Co、V、W、B、Zr、N、O、H、Sn、Pb、As、Sb、Bi、Ca、Mg、Zn、Se、Te、Ag、Cd、Ce、La、Y。

别名规则：`Fe^{b}$` → `Feb` → `Fe`；`Ni+Ta` → `Ni`；元素列必须有明确表头，否则不推断。

### 5.3 条件（facets）

`Record.condition` 是展示字符串，`Record.facets` 是规范结构。推荐 facet 与顺序：

```text
product_form / thickness / heat_treatment / specimen_state / direction / test_temperature / location
```

示例：`模锻件 / ≤100 / T6 / 平行于流线`、`2A14 / T6或T651或T652 / 切向`。

规则：

- 同一记录内不重复；
- 温度统一 `室温`、`650℃`、`-196℃`；
- 方向统一 `纵向/横向/切向/径向/轴向/高向/平行于流线/非平行于流线`；
- 位置只放取样位置，方法放 `InspectionItem` 或 `ClauseRecord`；
- 评测时 grade 相同且两侧 condition token 集合互为子集（交集非空）即视为兼容记录，报告用 `Condition relaxed` 单独计数。

## 6. 证据与缺失规则

1. 每个 `ExtractedValue` 必须有 `evidence_id`；`text` 值也一样。
2. `Evidence.quote` 必须非空，且能在对应页原文中定位。
3. 表格证据用 `table_id + row + col`（0 基）；条款证据用 `clause_id + quote`。
4. 源文明确写 `-` / `不要求` 时，用 `comparator=na` 或 `not_applicable`，不要留空值。
5. 找不到证据就不抽；用 `CoverageItem.status=missing` 报告，不允许模型猜值。
6. 证据不存在或 quote 为空 → L1 error，发布阻断。

## 7. 版本与兼容

- `SCHEMA_VERSION = "0.1.0"`；`schemas/v0/` 是冻结快照。
- 新增可选字段不升主版本；删除/改名/改变语义必须升版本并提供迁移脚本。
- 旧 `result.json` 必须可回读（Pydantic `extra="ignore"`）。
- 每次 prompt/recipe/model 变更后必须重跑黄金集；核心字段下降 >1pp 阻止合并。

## 8. 20 份文档映射

覆盖模板：`gb_t → product_full`、`gjb → gjb`、`enterprise → enterprise`、`agreement → technical_agreement`、`classification → classification`。

| 文档 | 类型 | 模板 | 表型（manifest 实测） | 结论 |
|---|---|---|---|---|
| qdu302_2015 | enterprise | enterprise | classification, mechanical, inspection, dimension | 可映射；化学表 not_applicable |
| gbt40303_2021 | gb_t | product_full | chemical, mechanical, inspection, dimension | 可映射；T4 力学表列错位待 M1.5 |
| gjb2057a_2018 | gjb | gjb | chemical, mechanical, inspection, classification, dimension | 可映射；T2 迷你集只标 6 行 |
| gbt1591_2018 | gb_t | product_full | chemical, mechanical, inspection, classification, dimension | 可映射；OCR 表头粘连 |
| gbt14992_2015 | classification | classification | chemical, classification | 可映射；PDF 文本层极薄 |
| gbt3191_1998 | gb_t | product_full | chemical, mechanical, inspection, classification, dimension | 可映射 |
| gbt3191_2010 | gb_t | product_full | chemical, mechanical, inspection, classification, dimension | 可映射；与 1998 版成对 |
| gbt1220_2007 | gb_t | product_full | chemical, mechanical, inspection, classification, dimension | 可映射 |
| gbt33084_2016 | gb_t | product_full | chemical, mechanical, inspection, classification | 可映射 |
| gbt3203_2016 | gb_t | product_full | chemical, mechanical, inspection, dimension | 可映射 |
| gbt3880_1_2012 | gb_t | product_full | chemical, mechanical, inspection, classification, dimension | 可映射 |
| gbt4437_1_2015 | gb_t | product_full | chemical, mechanical, inspection, classification, dimension | 可映射；混合文本层 |
| gbt6892_2015 | gb_t | product_full | chemical, mechanical, inspection, classification, dimension | 可映射；版式复杂 |
| gjb2294a_2014 | gjb | gjb | chemical, mechanical, inspection, dimension | 可映射 |
| gjb5301_2004 | gjb | gjb | chemical, mechanical, inspection, classification | 可映射 |
| gjb3325a_2019 | gjb | gjb | chemical, mechanical, inspection, classification | 可映射（heldout） |
| jx25_035 | agreement | technical_agreement | mechanical, inspection | 可映射；化学表转置 |
| mas7079_b | enterprise | enterprise | mechanical, inspection | 可映射（heldout） |
| qs10_0351_2004 | enterprise | enterprise | mechanical, inspection | 可映射（heldout） |
| sjx100_410_2019 | enterprise | enterprise | chemical | 可映射；表少（heldout） |

维度表在 v0 只要求 `TableGrid` 可解析，不要求类型化字段；因此“可映射”不等于“维度字段已抽取”。

## 9. 冻结检查清单

- [x] 20 份文档全部映射到契约与覆盖模板；
- [x] `schemas/v0/` 可导出 15 个 JSON Schema；
- [x] 黄金集 manifest 结构校验通过；
- [x] 20 份黄金集 draft 标注（60 表、149 记录、157 检验项、87 条款），1595 条证据 locator 已校验；
- [ ] 业务/领域签字（待人工）；
- [ ] 双人标注一致性报告（待领域专家）；
- [ ] 8 份数字原生文档（当前语料仅 6 份，缺口已记录）。
