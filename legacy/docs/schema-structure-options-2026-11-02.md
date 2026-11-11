# 最终抽取 Schema 结构与实现方案（2026-11-02）

> 目标：最终交付结构采用 hansonDoc_RAG 的 Schema 样式，但只保留业务真正需要的三块：**标准信息、项目信息、热处理信息**，不输出大量全空字段与空类别。
> 命名口径：类别名使用当前项目 `business_dictionary.hanson.json` 的业务词典 category 名称（用户已确认）。

## 1. hansonDoc_RAG 原始结构（只读调研结论）

调研对象：`grainuser@192.168.188.75:~/hansonDoc_RAG`（只读，未修改）。

### 1.1 模板层

hansonDoc_RAG 的模板是三层结构：

```text
schema_template (id, name)
  └─ schema_category (name/feature, return_type=array|object, name_source=manual|term_base, fixed_query)
       └─ schema_field (name, type, description, example, required, sort_order)
```

`name_source=term_base` 的类别会按术语集名称字段展开成多个类别。当前“产品标准抽取模板”（`6e2ad0d7-f92a-4663-b5cf-ae01c2378fa7`）展开后包含：

- `标准信息`（object，固定字段：标准名称、标准编号）
- `热处理制度`（array，固定字段：材料牌号、工艺名称、保温温度、保温时间、冷却介质、工序名称、介质温度、装炉温度、升温速率、降温速率、出炉温度、项目大类）
- 术语集展开出的检测项目类别：`化学成分`、`室温拉伸`、`高温拉伸`、`高温光滑持久`、`夏比冲击`、`布氏硬度`、`低倍`、`高倍组织` 等；每类字段为：项目名称、材料牌号、标准要求、单位、试验方法、试验温度、位置、方向、尺寸厚度、试样状态、取样数量、取样说明、锻件类型。

### 1.2 结果层

`pipeline._result()` 固定输出：

```json
{
  "schema_template_id": "...",
  "schema_name": "产品标准抽取模板",
  "categories": [
    {
      "feature": "化学成分",
      "records": [{"项目名称": "...", "材料牌号": "...", "标准要求": "...", "单位": "%"}],
      "rejected": [],
      "missing_fields": ["..."],
      "hit_score": null,
      "hit_count": 11
    }
  ],
  "summary": {
    "total_records": 18,
    "kept_categories": 5,
    "categories_attempted": 5,
    "skipped": [],
    "recall": {"mode": "loose", "participated": 5, "kept": 5, "skipped_count": 0, "score_bands": {}}
  },
  "timing": {"total_sec": 18.12}
}
```

关键规则：

- 只保留 `records` 或 `rejected` 非空的类别（`non_empty` 过滤）；术语集无名称时进入 `summary.skipped`。
- `missing_fields` 只统计模板中 `required=true` 且所有记录均为空/缺省的字段（`llm_extractor.missing_required_fields`）。
- `rejected` 来自规则组后处理/校验脚本淘汰的记录；`retried/retry` 仅在 0 条重排重试时出现。
- 记录字段不固定，完全由模板字段决定。

### 1.3 与当前项目的问题对照

当前 `hanson JSON` 导出顶层已经模仿了该结构，但存在：

| 问题 | 现状 | 影响 |
| --- | --- | --- |
| 类别来源 | 按表型/属性猜，未按 `item_inventory_aligned.json` 的项目大类分组 | 漏类别、类别错位 |
| 20℃ 数据 | T3 的室温数据被归入“高温拉伸” | 语义错误 |
| 标准名称 | 带上传 uuid 前缀 | 交付不可用 |
| 空字段 | 13 个字段全部输出，大量为空 | 与“不要无用字段”冲突 |
| missing_fields | 统计全部字段 | 与 hansonDoc 语义不一致 |
| 空类别 | 热处理等空类别仍输出 | 噪声 |

## 2. 目标 Schema（精简三段式）

### 2.1 顶层

```json
{
  "schema_template_id": "6e2ad0d7-f92a-4663-b5cf-ae01c2378fa7",
  "schema_name": "产品标准抽取模板（精简）",
  "categories": [ ... ],
  "summary": {"total_records": 0, "kept_categories": 0},
  "timing": {"total_sec": 0.0}
}
```

### 2.2 三个固定区块

| 区块 | `feature` | 返回类型 | 必填字段 | 可选字段（有值才输出） |
| --- | --- | --- | --- | --- |
| 标准信息 | `标准信息` | object（单条 records） | 标准名称、标准编号 | — |
| 项目信息 | 当前文档实际存在的项目大类（如 `化学成分`、`室温拉伸`、`高温拉伸`、`布氏硬度`、`夏比冲击`） | array | 项目名称、材料牌号、标准要求；数值型项目另需 单位 | 试验方法、试验温度、位置、方向、尺寸厚度、试样状态、取样数量、取样说明、锻件类型 |
| 热处理信息 | `热处理制度` | array | 材料牌号、工序名称、保温温度、保温时间 | 工艺名称、冷却介质、装炉温度、出炉温度、升温速率、降温速率、介质温度 |

规则：

1. **类别级裁剪**：文档中没有的项目大类不输出；标准信息始终输出；热处理无数据时不输出该类别。
2. **字段级裁剪**：某类别下所有记录均为空的可选字段，不写入该类别任何记录；核心字段始终保留（无值写 `""`）。
3. **记录级裁剪**：同一条记录里可选字段为空则不写该 key，避免大量 `""`。
4. `missing_fields`：仅针对必填字段统计。
5. `hit_count`：该类别记录数；`hit_score`、`rejected`、`recall`、`score_bands` 等对交付无用的字段不输出。
6. 标准名称：从 `outline.json` 的文档标题识别，去除上传文件名前缀；标准编号取 `document.standard_no`。

### 2.3 示例（TA15 文档，节选）

```json
{
  "schema_template_id": "6e2ad0d7-f92a-4663-b5cf-ae01c2378fa7",
  "schema_name": "产品标准抽取模板（精简）",
  "categories": [
    {
      "feature": "标准信息",
      "records": [{"标准名称": "TA15钛合金锻制棒材", "标准编号": "Q/S 10-0351-2004"}],
      "missing_fields": [],
      "hit_count": 1
    },
    {
      "feature": "化学成分",
      "records": [
        {"项目名称": "Al", "材料牌号": "TA15", "标准要求": "5.50~7.00", "单位": "%", "试验方法": "GB/T 4698"},
        {"项目名称": "Fe", "材料牌号": "TA15", "标准要求": "≤0.25", "单位": "%", "试验方法": "GB/T 4698"}
      ],
      "missing_fields": [],
      "hit_count": 11
    },
    {
      "feature": "室温拉伸",
      "records": [
        {"项目名称": "抗拉强度", "材料牌号": "TA15", "标准要求": "≥885", "单位": "MPa", "试验方法": "GB/T 228.1-2021", "试验温度": "室温", "方向": "横向"}
      ],
      "missing_fields": [],
      "hit_count": 3
    },
    {
      "feature": "布氏硬度",
      "records": [
        {"项目名称": "布氏硬度", "材料牌号": "TA15", "标准要求": "3.3~3.8", "单位": "HBW", "试验方法": "GB/T 231.1"}
      ],
      "missing_fields": ["单位"],
      "hit_count": 1
    }
  ],
  "summary": {"total_records": 16, "kept_categories": 4},
  "timing": {"total_sec": 18.12}
}
```

## 3. 实现方案（多选一）

### 方案 A：精简三段 + 动态项目类别（推荐，最优）

- 标准信息固定两条；项目信息按 `item_inventory_aligned.json` 的 `business_category_name` 分组（为空时按 `item_family + facets` 回退），只输出文档中实际存在的类别；热处理信息仅在有数据时输出。
- 字段级裁剪：按第 2.2 节规则，核心字段固定、可选字段有值才输出。
- 产出位置：新增 `schema_result.json` 产物；`hanson JSON` 导出与结果接口复用同一投影。
- 优点：最贴合“当前文档中有的项目大类及字段”，无空类别、无空字段；类别结构与 hansonDoc 一致；可直接从现有 `ItemInventory` 生成，不需要改抽取链路。
- 缺点：类别字段集合随文档变化，消费方需容忍动态 key（但核心 key 稳定）。
- 改动：`configs/schema_templates/product_standard.json` 增加 `template_id` 与 `slim=true` 开关；`schema_projection.py` 新增 `project_hanson_schema`；`export_hanson_schema.py` 与 API 导出改为调用该投影；可选新增结果接口与前端“Schema”页签。

### 方案 B：固定三段 + 项目信息扁平化

- 固定三类：`标准信息`、`项目信息`、`热处理信息`。
- `项目信息` 不按项目大类拆 category，所有检测项放进一个数组，每条记录增加 `项目大类` 字段。
- 字段固定为第 2.2 节的全部字段（不做字段裁剪）。
- 优点：结构最稳定，消费方实现简单；适合直接入库或表格导出。
- 缺点：失去按项目大类浏览的能力；仍会输出空字段，与“不要无用字段”部分冲突。
- 改动：只需新增一个导出投影，不涉及类别展开。

### 方案 C：完全对齐 hansonDoc_RAG（不裁剪）

- 保持 `rejected`、`hit_score`、`summary.recall/score_bands/skipped`，项目类别全部展开、13 个字段全输出。
- 优点：与 hansonDoc_RAG 1:1，可直接复用其前端与下游工具。
- 缺点：空类别、空字段多，正是本轮反馈要解决的问题；结构噪声大。
- 改动：修正现有 `export_hanson_schema.py` 的分组与字段映射即可。

### 方案 D：精简三段 + 项目固定核心字段

- 标准信息、热处理信息同方案 A；项目信息按项目大类分组，但每条记录只保留 6 个核心字段：项目名称、材料牌号、标准要求、单位、试验方法、试验温度。
- 优点：输出最干净，字段最稳定；适合只关心“项目-要求-方法-温度”的场景。
- 缺点：丢失方向、尺寸厚度、取样数量、试样状态等业务属性，矩阵型标准的维度信息无法体现（与项目记忆中的“多维度条件不得遗漏”冲突）。
- 改动：同方案 A，字段白名单更小。

### 方案对比

| 维度 | A（推荐） | B | C | D |
| --- | --- | --- | --- | --- |
| 标准信息 | 固定 | 固定 | 固定 | 固定 |
| 项目信息分组 | 按文档实际类别 | 扁平单数组 | 全类别展开 | 按文档实际类别 |
| 空类别 | 不输出 | 不输出 | 输出 | 不输出 |
| 空字段 | 不输出 | 输出 | 输出 | 仅核心字段 |
| 业务维度字段 | 有值保留 | 全保留 | 全保留 | 丢弃 |
| 与 hansonDoc 相似度 | 高 | 中 | 最高 | 中 |
| 消费复杂度 | 低 | 最低 | 高 | 最低 |
| 推荐度 | ★★★★★ | ★★★ | ★★ | ★★★ |

## 4. 选定后的落地步骤（以方案 A 为例）

1. 模板：`configs/schema_templates/product_standard.json` 增加 `template_id` 与 `slim` 配置，字段保留现有定义。
2. 投影：`metal_doc_agent/schema_projection.py` 新增 `project_hanson_schema(job_dir, template, timing_seconds)`：
   - 读取 `result.json`、`item_inventory_aligned.json`、`outline.json`、`trace.json`；
   - 标准信息：`_standard_name()` + `document.standard_no`；
   - 项目信息：按 `business_category_name` 分组，调用现有 `_property_records` / `_format_value` / `_method_number` 生成记录；按第 2.2 节裁剪字段；
   - 热处理：复用 `_build_heat_treatment`，有数据才输出；
   - 计算 `missing_fields`（required-only）、`summary`、`timing`。
3. 导出：`tools/export_hanson_schema.py` 的 `build_payload` 改为调用该投影；API `export_bytes` 传入 `job_dir`。
4. 可选：新增 `GET /v1/documents/{id}/result/schema`，结果页增加“Schema 结果”页签，按 category 展示 records/missing_fields。
5. 验证：用 TA15 作业（`51c4854b8462`）复跑投影，核对类别为 标准信息/化学成分/室温拉伸/高温拉伸/布氏硬度，且无 20℃ 数据落入高温拉伸；补充 `tests/test_schema_projection.py` 的结构断言；前端导出回归。

## 5. 待确认

选择方案 A / B / C / D。确认后按对应范围实现并复跑 TA15 与 E2E 导出验证。

## 6. 方案 A 实施记录（2026-11-02）

已按方案 A 落地：

| 项 | 实现 |
| --- | --- |
| 模板 | `metal-doc-agent/configs/schema_templates/product_standard.json` 增加 `template_id` 与 `slim=true` |
| 投影 | `metal_doc_agent/schema_projection.py` 新增 `project_hanson_schema(job_dir, template)` |
| 管线产物 | `pipeline.py` 解析结束写出 `schema_result.json`，并登记到 `artifacts.json` |
| 结果接口 | `GET /v1/documents/{document_id}/result/schema`，优先读取产物，缺失时实时投影 |
| 导出 | `hanson JSON` 优先读取 `schema_result.json`，缺失时调用同一投影 |
| 前端 | 本次未新增页签，导出文件即为最终结构 |

投影规则：

- 类别来源：`item_inventory_aligned.json` 的 `business_category_name`；为空时按 `item_family + facets` 回退到业务词典类别名。
- 只输出当前文档出现的项目类别；标准信息始终输出；热处理信息仅在有数据时输出。
- 项目类别核心字段：项目名称、材料牌号、标准要求；数值型项目缺单位时在 `missing_fields` 记录 `单位`。
- 可选字段（试验方法、试验温度、位置、方向、尺寸厚度、试样状态、取样数量、取样说明、锻件类型）有值才写入。
- 热处理字段：材料牌号、工序名称、保温温度、保温时间为固定字段；工艺名称、冷却介质、装炉温度、出炉温度、升温速率、降温速率、介质温度有值才写入。
- `missing_fields` 只统计必填字段；不输出 `rejected`、`hit_score`、`recall`、`score_bands`。

实测结果：

- TA15（`Q/S 10-0351-2004`）：13 个类别、26 条记录；室温数据只落在“室温拉伸”，500℃ 数据落在“高温拉伸”；标准名称为“TA15 钛合金锻制棒材”。
- GB/T 2965-2007：11 个项目类别 + 热处理制度 26 条；热处理从状态/热处理表解析出牌号、温度区间、保温时间、冷却介质。

