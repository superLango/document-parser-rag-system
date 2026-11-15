# 新旧项目抽取能力对齐实施方案

> 版本：2026-11-14  
> 基线：parser `1.0.54`、30 份金标、当前 5 份中文复测结果  
> 目标：在不破坏现有服务链路和确定性的前提下，把旧项目已有、新项目缺失的“正文条款 / 检验清单 / 定性项目 / 引用标准 / 词典对齐 / 模型兜底”能力补齐。

---

## 0. 结论先行

新项目当前强在**表格矩阵 + 配方路由 + 沙箱确定性执行 + 自动修复闭环**，弱在**表格之外的文档理解**。旧项目的能力可以归纳为 6 个抽取维度，新项目目前只完整覆盖了第 1 个：

| 维度 | 旧项目 | 新项目现状 | 优先级 |
|---|---|---|---|
| 表格矩阵 | `matrix.py` / `ir_matrix.py`，多表头、合并单元格、行列归一 | `builtin.py` + 配方绑定，主体可用 | 维持 + 复杂表增强 |
| 正文条款 | `clauses.py`，条款切分 + 要求/方向/取样/方法字段 | 仅方法/取样正则，无条款语料 | **P0** |
| 检验与非记录表 | `nonrecord.py`，检验项目、分类项、定性项 | 已补检验项目元数据 | **P1** |
| 项目清单 | `ItemInventoryEntry`，来源含表格/条款/引用 | 只从表格属性反推 | **P0** |
| 引用标准与方法 | `references.py` + `method_binding.py` | 条款号 + 正文正则 | **P1** |
| 词典与业务对齐 | 业务词典 + canonicalize | 配方 measure 别名 | **P2** |
| 模型兜底 | `qwen.py` 复杂表/条款抽取 | 解析阶段无模型兜底 | **P2** |

实施顺序建议：**条款语料 + 项目清单（P0）→ 检验/分类/定性（P1）→ 引用标准 + 词典对齐（P1/P2）→ 模型兜底（P2）**。

---

## 1. 现状与差距

### 1.1 新项目现有架构

```
OCR 服务
  └─ ocr.json / markdown.md / tables.json / layout.json
        │
orchestration
  ├─ routing：配方路由（table → recipe_id/version）
  ├─ sandbox：parser 资产（builtin.py / strategies.py）+ 配方 manifest
  │     └─ records.json / result.json / diagnostics.json / evidence.jsonl
  ├─ review：DOC-* 门禁 + 模型审核
  └─ feedback：triage → repairability → L1/L2/L3 → 验证/晋升
        │
web：文档库 / 解析详情 / 审核 / 反馈 / 时间线 / 配方版本
```

关键约束：

- 沙箱执行镜像 `hanson-sandbox-runtime:local` 只运行标准库代码，parser 资产从 recipe-registry 热加载。
- parser 资产通过 `scripts/assets/publish_parser_asset.py` 发布，按版本 + 通道（candidate/stable）管理。
- `reparse` 已支持 `reuse_ocr=true`，解析器升级不必重跑 OCR。
- 最终 schema 仍是 13 字段（项目名称、材料牌号、标准要求、单位、试验方法、试验温度、位置、方向、尺寸厚度、试样状态、取样数量、取样说明、锻件类型）。

### 1.2 旧项目已有、新项目缺失的能力

| 旧模块 | 能力 | 新项目缺口 |
|---|---|---|
| `extraction/clauses.py` | 条款切分；抽 requirement / direction / sample_quantity / sample_location / method | 没有条款语料，正文要求无法进入最终行 |
| `extraction/nonrecord.py` | 检验项目表、分类项（牌号/状态/含义）、定性项 | 只有检验项目元数据；分类项、定性项没有 |
| `ItemInventoryEntry` | 项目清单，来源 `inspection_table / property_table / clause / reference` | 只从表格属性反推，正文列出的项目会漏 |
| `references.py` + `method_binding.py` | 引用标准清单、方法绑定、版本/替代关系 | 只有条款号/正则，没有引用图和引用解析 |
| `canonicalize/` + 业务词典 | 项目/方法/属性/项目大类归一 | 只有配方 measure 别名 |
| `extraction/qwen.py` | 复杂表格/条款模型兜底 | 解析阶段无模型兜底，模型只在审核/修复阶段 |
| `schema_projection.py` | 把 inventory + clauses + inspections + records 投影成最终 schema | 目前是 `apply_document_metadata` 的局部实现 |

### 1.3 当前 5 份文档已验证的缺口

- GB/T 24627：取样位置/取样说明只在正文，已用正文规则补上。
- HB 20079：合并列“取样数量和取样部位”已补。
- 仍缺：GB/T 1591 冲击/上屈服等表格列，HB 洛氏，GB/T 5231 复合列；这些属于**矩阵层**，不是正文层。

---

## 2. 目标架构

### 2.1 分层设计

```
┌─────────────────────────────────────────────────────────────┐
│ OCR（不变）                                                  │
└─────────────────────────────────────────────────────────────┘
              │ ocr.json / markdown.md / tables.json
              ▼
┌─────────────────────────────────────────────────────────────┐
│ sandbox 文档理解层（新增，纯标准库、确定性）                 │
│  clauses.py        → clauses.json                            │
│  nonrecord.py      → inspections / classifications /          │
│                      qualitative_items                       │
│  inventory.py      → inventory.json（项目清单）              │
│  references.py     → references.json（引用标准图）           │
│  projection.py     → 最终 records + document_intelligence    │
└─────────────────────────────────────────────────────────────┘
              │ records.json / document_intelligence.json
              ▼
┌─────────────────────────────────────────────────────────────┐
│ orchestration                                                │
│  review：条款/定性/引用/矩阵门禁                             │
│  feedback：把 clause/inventory 证据带入修复上下文            │
│  model fallback：覆盖不足时调用 agent（有预算、有证据校验）  │
└─────────────────────────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────────────────────┐
│ web：结果表 + “正文要求/定性项目”分区 + 条款/引用追溯面板     │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 新增产物

| 产物 | 角色 | 内容 |
|---|---|---|
| `clauses.json` | 条款语料 | clause_id / title / kind / page_no / text / fields / evidence |
| `inventory.json` | 项目清单 | item / feature / family / source / clause_id / table_id / requirement / method / sampling |
| `references.json` | 引用标准图 | 引用原文、标准号、版本、关系、是否解析、替代关系 |
| `document_intelligence.json` | 汇总 | inspections / classifications / qualitative_items / inventory / references / coverage |
| `records.json` | 最终项目 | 现有 13 字段记录；新增 `profile=qualitative` 的正文/定性记录 |

产物统一使用版本化 schema：

- `document-clauses/1`
- `document-inventory/1`
- `document-references/1`
- `document-intelligence/1`

### 2.3 数据流与优先级

字段填充优先级（高 → 低）：

1. 性能表单元格（配方矩阵）
2. 检验项目表（取样/方法/条款号）
3. 正文条款（要求/取样/方法）
4. 业务词典/历史案例
5. 模型兜底（必须带 evidence，不覆盖高优先级值）

任何一层都不允许编造原文没有的数值；文本要求保留原文句子和 evidence。

---

## 3. 工作流与任务拆分

### WS1 条款语料（P0）

**目标**：把正文条款变成结构化语料，供项目清单、方法和取样使用。

任务：

1. 新增 `services/sandbox/runtime/clauses.py`，从 `legacy/.../extraction/clauses.py` 裁剪移植：
   - 条款切分：标题正则、目录行过滤、跨页块合并；
   - 条款类型：scope / normative_reference / technical_requirement / inspection / sampling / test_method / delivery / packaging；
   - 字段抽取：requirement / direction / sample_quantity / sample_location / method；
   - 证据：clause_id、page_no、quote。
2. `runner.py` 在 OCR 读取后调用 `extract_clauses(ocr)`，写 `clauses.json`。
3. `publish_parser_asset.py` 的 `PARSER_FILES` 增加 `clauses.py`。
4. 单元测试：条款切分、跨页合并、字段抽取、目录行过滤。

**退出标准**：

- 5 份中文文档条款数 ≥ 旧项目同文档条款数的 90%；
- 条款字段抽取有 evidence；
- 解析耗时增加 < 200ms/份。

### WS2 检验/分类/定性项（P1）

**目标**：非记录表里的项目不再被丢掉。

任务：

1. 新增 `services/sandbox/runtime/nonrecord.py`，移植：
   - 检验项目表 → `InspectionItem`（已有 `_inspection_items`，合并到统一模型）；
   - 分类项 → `ClassificationItem`（grade / old_grade / state / meaning）；
   - 定性项 → `qualitative_items`（晶粒度、低倍、高倍、非金属夹杂、超声波、铁素体、外观、尺寸等）。
2. 定性项识别规则：
   - 条款/表格中出现“应进行/应检验/应符合/不低于/不大于”等要求标记；
   - 项目名命中特征词典；
   - 有明确要求文本或表号引用。
3. 输出 `document_intelligence.json` 的 `classifications` / `qualitative_items`。
4. 单元测试：HB 表 9 检验项目、GB/T 24627 正文项目、定性项抽取。

**退出标准**：

- 有检验表的文档，检验项目覆盖 ≥ 95%；
- 定性项不重复、不吞并数值项；
- 所有定性项有 source（clause/table）和 evidence。

### WS3 项目清单 inventory（P0）

**目标**：形成“文档要求做哪些检测项目”的权威清单，驱动最终行投影。

任务：

1. 新增 `services/sandbox/runtime/inventory.py`：
   - 合并来源：`inspection_table`、`property_table`、`clause`、`reference`；
   - 去重键：feature + 项目名 + 条件；
   - 字段：item / feature / family / source / clause_id / table_id / requirement / method / sampling / status；
   - 状态：confirmed / probable / new / ambiguous / not_applicable。
2. 与配方矩阵对齐：
   - 表格有记录 → confirmed；
   - 只有条款 → probable；
   - 只有引用标准 → new；
   - 冲突 → ambiguous，交审核。
3. 输出 `inventory.json`，并在 `document_intelligence.json` 中给出 coverage。
4. 单元测试：正文项目、表格项目、重复合并、冲突标记。

**退出标准**：

- 正文单独列出的项目能进入 inventory；
- inventory 与 records 的 feature 对齐率 ≥ 95%；
- 不把“说明/目录/引用文件”误判为检测项目。

### WS4 引用标准与方法绑定（P1）

**目标**：把“见 8.2”“按 GB/T 228.1”变成可追溯的方法。

任务：

1. 新增 `services/sandbox/runtime/references.py`：
   - 规范性引用文件清单解析（标准号、名称、版本）；
   - 条款/表格中的引用识别；
   - 关系：normative / informative / table_note / clause；
   - 解析状态：resolved / unresolved / superseded。
2. 方法绑定：
   - 特征 → 方法优先级（化学成分多方法、室温/高温拉伸、冲击、硬度、断裂韧度等）；
   - 条款号 → 条款正文 → 标准号；
   - 正文句子 → 方法（现有 `_prose_methods` 升级为统一入口）。
3. 输出 `references.json`，方法写入 records 的 `meta.试验方法`。
4. 单元测试：GB/T 1591 8.2、GB/T 14976 9.1、HB 4.3.1/4.3.2。

**退出标准**：

- 条款引用解析率 ≥ 90%；
- 方法字段填充率 ≥ 80%（有方法可填的项目）；
- 不把取样标准（GB/T 20066/2975）误当试验方法。

### WS5 投影层 projection（P0）

**目标**：替代当前分散的 `apply_document_metadata`，统一生成最终 schema。

任务：

1. 新增 `services/sandbox/runtime/projection.py`：
   - 输入：records、inventory、clauses、inspections、classifications、references；
   - 输出：最终 records（13 字段）+ qualitative records；
   - 规则：字段优先级、去重、条件展开、单位/操作符补齐。
2. 数据模型：
   - 数值项：现有 `profile`（chemical/mechanical/heat）；
   - 定性项：`profile="qualitative"`，property 名=项目名，`raw`=要求文本，`meta` 带方法/取样；
   - 正文项目：`source={"clause_id": "...", "page_no": ...}`。
3. `runner.py` 在合并/去重后调用 projection，移除旧 `apply_document_metadata` 的散落逻辑。
4. 单元测试：数值 + 定性混合、正文项目、字段优先级。

**退出标准**：

- 同一文档重复解析结果稳定；
- 字段来源可追溯；
- 现有 5 份金标 F1 不下降超过 0.01。

### WS6 业务词典对齐（P2）

**目标**：新项目名/新方法名能归一到业务词典。

任务：

1. 新增 dictionary 资产类型（recipe-registry）：
   - `kind=dictionary`，条目：item / method / property / category；
   - 字段：business_code / business_name / aliases / standard_no / status / version。
2. 迁移旧词典：
   - 从 `legacy/metal-doc-agent/configs/dictionaries/`、`business_dictionary.json` 生成首版；
   - 建立版本、通道、回滚。
3. 在 projection 中做 canonicalize：
   - 项目名 → feature / 项目大类；
   - 方法名 → 标准号；
   - 未命中标记 `new`，不静默新建。
4. 单元测试：别名匹配、冲突、未命中。

**退出标准**：

- 业务词典命中率 ≥ 90%（针对词典内已有词）；
- 未命中项有清单，不阻塞解析。

### WS7 模型兜底（P2）

**目标**：确定性规则覆盖不足时，用模型补，但不破坏可追溯性。

任务：

1. 触发条件（任一）：
   - matrix diagnostics 高（对齐失败/空表/表头异常）；
   - clause/inventory coverage 低于阈值；
   - review 发现 `DOC-*` 且 repairability 判定需要更多证据。
2. 调用 agent 服务，输入：
   - 目标表/条款的 OCR 片段（截断）；
   - 现有 inventory/clauses 摘要；
   - schema 字段约束；
   - 输出 JSON schema + evidence 要求。
3. 输出校验：
   - 必须在原文中找到 quote；
   - 数值必须能在单元格/条款中定位；
   - 不覆盖确定性层的高优先级值；
   - 失败则丢弃并记录 diagnostics。
4. 预算：沿用 feedback 的 token/wall-time 预算，单文档上限可配。

**退出标准**：

- 模型结果全部带 evidence；
- 不增加静默错误率；
- 关闭开关后行为与确定性层一致。

### WS8 审核、评测与前端（P0/P1）

**目标**：新增能力可见、可评测、可审核。

任务：

1. review 规则：
   - `DOC-CLAUSE-UNMAPPED`：条款项目未投影；
   - `DOC-QUALITATIVE-MISSING`：应做定性项但无记录；
   - `DOC-REFERENCE-UNRESOLVED`：引用标准未解析；
   - `DOC-INVENTORY-CONFLICT`：表格与条款项目冲突。
2. gold_eval：
   - 现有可能量项 F1 不变；
   - 新增定性项覆盖率、正文项目召回率、方法/取样填充率；
   - 文本要求不进入数值 F1，单独统计。
3. 前端：
   - 结果表新增“正文/定性项目”分区；
   - 列仍为 13 字段；
   - 增加“条款/引用标准”追溯面板；
   - 反馈入口支持对定性项发起反馈。
4. 测试：Playwright 页面校验 + 金标回归。

**退出标准**：

- 5 份中文页面可见正文/定性项目；
- 金标指标不下降；
- 新增指标有报告。

### WS9 发布、灰度与回滚（贯穿）

任务：

1. 解析器资产版本：`1.1.x`（clauses/inventory/projection 一起发布）。
2. 功能开关：
   - `DOCUMENT_INTELLIGENCE_ENABLED`
   - `CLAUSES_ENABLED`
   - `QUALITATIVE_ITEMS_ENABLED`
   - `DICTIONARY_ALIGNMENT_ENABLED`
   - `MODEL_FALLBACK_ENABLED`
3. 发布流程：
   - candidate 通道 → 5 份抽样 → 30 份金标回归 → stable；
   - 用 `reparse + reuse_ocr=true` 做快速回放；
   - 失败回滚：pin 回上一个 parser 版本 / 关闭开关。
4. 监控：
   - 解析耗时、条款数、inventory 覆盖率、未解析引用数、定性项数；
   - review 命中分布、自动修复成功率。

---

## 4. 阶段与里程碑

| 阶段 | 内容 | 依赖 | 退出标准 |
|---|---|---|---|
| 阶段 1（P0） | 条款语料 + inventory + projection 骨架 + 前端“正文/定性”分区 + gold_eval 新指标 | 无 | 5 份中文正文项目可见；F1 不降 |
| 阶段 2（P1） | 检验/分类/定性项 + 引用标准/方法绑定 + review 规则 | 阶段 1 | 定性项覆盖；引用解析率 ≥ 90% |
| 阶段 3（P2） | 业务词典 + 模型兜底 + 复杂矩阵增强 | 阶段 2 | 词典命中率 ≥ 90%；模型结果全带 evidence |
| 阶段 4 | 30 份全量回归 + 灰度 + stable 发布 | 阶段 3 | 金标门槛通过；可回滚 |

---

## 5. 数据契约（示例）

### 5.1 `clauses.json`

```json
{
  "schema_version": "document-clauses/1",
  "clauses": [
    {
      "clause_id": "8.2",
      "title": "钢的化学成分试验",
      "kind": "test_method",
      "page_no": 15,
      "text": "钢的化学成分试验一般按 GB/T 4336、GB/T 20123……",
      "fields": {
        "requirement": {"text": "按 GB/T 4336……", "evidence": "8.2"},
        "method": {"text": "GB/T 4336、GB/T 20123", "evidence": "8.2"}
      },
      "evidence": ["8.2:15"]
    }
  ]
}
```

### 5.2 `inventory.json`

```json
{
  "schema_version": "document-inventory/1",
  "items": [
    {
      "item": "化学成分",
      "feature": "化学成分",
      "family": "chemical_composition",
      "source": "inspection_table",
      "table_id": "T24",
      "clause_id": "8.2",
      "requirement": null,
      "method": "GB/T 4336、GB/T 20123",
      "sampling": {"数量": "1", "说明": "1个/炉", "位置": "按 GB/T 20066 的规定取样"},
      "status": "confirmed"
    }
  ],
  "coverage": {"required": 12, "covered": 10, "rate": 0.8333}
}
```

### 5.3 `document_intelligence.json`

```json
{
  "schema_version": "document-intelligence/1",
  "inspections": [],
  "classifications": [],
  "qualitative_items": [
    {
      "feature": "晶粒度",
      "requirement": "晶粒度应不低于5级",
      "method": "GB/T 6394",
      "sampling": {"位置": "按 GB/T 2975 的规定取样"},
      "source": {"clause_id": "7.6", "page_no": 10}
    }
  ],
  "references": [],
  "coverage": {"clauses": 42, "inventory": 12, "qualitative": 4}
}
```

### 5.4 定性记录

```json
{
  "record_id": "DOC-Q1",
  "profile": "qualitative",
  "grade": "全部牌号",
  "conditions": {"试验方法": "GB/T 6394", "位置": "按 GB/T 2975 的规定取样"},
  "properties": {
    "晶粒度": {
      "value": null,
      "raw": "晶粒度应不低于5级",
      "operator": null,
      "unit": "",
      "meta": {
        "试验方法": "GB/T 6394",
        "位置": "按 GB/T 2975 的规定取样",
        "取样数量": "1",
        "取样说明": "每批抽检1件"
      }
    }
  },
  "source": {"clause_id": "7.6", "page_no": 10}
}
```

---

## 6. 字段来源优先级与证据

| 字段 | 第一来源 | 第二来源 | 第三来源 | 禁止 |
|---|---|---|---|---|
| 项目名称 | 表格表头/属性 | 检验项目表 | 条款 | 模型臆造 |
| 材料牌号 | 表格行键 | 文档级牌号推断 | 条款 | 用文件号当牌号 |
| 标准要求 | 表格单元格 | 条款要求句 | 模型（带 quote） | 编造数值 |
| 单位 | 表头/单位行 | 配方绑定 | 条款 | 把量纲当单位 |
| 试验方法 | 检验表方法列 | 条款号引用 | 正文方法句 | 取样标准混入 |
| 取样数量 | 检验表数量列 | 正文“每批/每炉” | 条款 | 把百分比当件数 |
| 取样说明 | 检验表部位列 | 正文取样句 | 条款 | 把表号当数量 |
| 位置/方向/尺寸/温度/状态 | 表格条件列 | 表头路径 | 条款 | 用牌号/文件号填充 |

所有字段写入 `meta` 或 `source` 时必须带 evidence（table_id + row/col 或 clause_id + page + quote）。

---

## 7. 质量门禁与指标

### 7.1 既有指标（不回归）

- 数值项 F1、静默错误率、单位准确率、覆盖率；
- 5 份中文基线：F1 0.7012、静默 4.97%、单位 99.27%、覆盖率 100%。

### 7.2 新增指标

| 指标 | 定义 | 目标 |
|---|---|---|
| 条款覆盖率 | 抽取条款数 / 旧项目同文档条款数 | ≥ 90% |
| Inventory 覆盖率 | inventory 覆盖项目 / 应有项目 | ≥ 95% |
| 正文项目召回 | 正文单独列出的项目被抽取比例 | ≥ 85% |
| 定性项覆盖率 | 定性项有记录 / 应做定性项 | ≥ 85% |
| 方法填充率 | 有方法可填的行 / 应有方法行 | ≥ 80% |
| 取样字段填充率 | 有取样信息可填的行 / 应有取样行 | ≥ 80% |
| 引用解析率 | resolved 引用 / 全部引用 | ≥ 90% |
| 词典命中率 | 命中业务词典项目 / 词典内项目 | ≥ 90% |
| 证据完整率 | 带 evidence 的新增字段 / 新增字段 | 100% |

### 7.3 回归门禁

- 30 份金标：F1 不低于基线 -0.01，静默率不高于基线 +1%；
- 5 份中文：F1 不低于基线 -0.01；
- 解析耗时（不含 OCR）< 3s/份；
- 关闭新开关时行为与基线一致。

---

## 8. 发布、灰度与回滚

1. **candidate 发布**：parser `1.1.x` candidate，只对抽样文档生效。
2. **抽样验证**：5 份中文 + 5 份英文/ISO/ASTM，检查条款、inventory、定性项、字段填充。
3. **30 份回归**：`gold_eval` + 新增指标报告。
4. **灰度**：按文档白名单/比例开启 `DOCUMENT_INTELLIGENCE_ENABLED`。
5. **stable 发布**：promote parser 资产；更新 `.env.example` 和部署配置。
6. **回滚**：
   - parser 版本 pin 回上一版；
   - 关闭功能开关；
   - `reparse + reuse_ocr=true` 快速恢复，不重跑 OCR。

---

## 9. 风险与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| 定性项目增加导致精确率下降 | 金标 F1 下降 | 只对明确要求项生成；默认开关；单独指标统计；不进入数值 F1 |
| OCR 噪声导致条款/引用误判 | 错误方法/取样 | 强制 evidence；低置信度进 review；不覆盖高优先级值 |
| 条款切分受 OCR 编号空格影响 | 条款漏抽 | 编号归一化（`8. 1` → `8.1`）、目录行过滤、跨页合并 |
| 多来源字段冲突 | 数据不一致 | 固定优先级；冲突标记 `ambiguous`；review 规则 |
| parser 资产变大/变慢 | 解析超时 | 纯标准库、按需解析、性能门禁 < 3s |
| 模型兜底不可控 | 幻觉/成本 | 预算、evidence 校验、确定性优先、开关可关 |
| 契约变更影响前端/评测 | 兼容性问题 | 产物版本化；旧字段保留；灰度验证 |

---

## 10. 验收清单

- [ ] `clauses.json` 产出，条款数/字段达到目标；
- [ ] `inventory.json` 产出，正文项目可进入清单；
- [ ] 定性项目（晶粒度/低倍/非金属夹杂/超声波/铁素体等）可生成记录；
- [ ] 分类项（牌号/状态/含义）可抽取；
- [ ] 引用标准图产出，方法绑定可用；
- [ ] projection 统一生成 13 字段记录；
- [ ] 业务词典可版本化、可回滚；
- [ ] 模型兜底带 evidence、可关闭；
- [ ] 前端显示“正文/定性项目”和追溯信息；
- [ ] 30 份金标回归通过；
- [ ] 5 份中文页面可审核；
- [ ] 发布/回滚演练完成。

---

## 11. 边界与不做

- 不在沙箱内引入第三方库或网络调用；
- 不让模型直接写最终值，模型结果必须经过 evidence 校验；
- 不为了“看起来全”而编造原文没有的项目/数值；
- 不改变现有 13 字段 schema 的主结构，只增加来源与追溯信息；
- 不重跑 OCR 做日常回归，统一用 `reparse + reuse_ocr=true`。
