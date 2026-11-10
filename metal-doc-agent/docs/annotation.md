# 黄金集标注规范（M0-04）

> 适用：`goldset/v0` 及后续版本。
> 标注文件：`goldset/v0/docs/{doc_id}.json`；清单：`goldset/v0/manifest.json`。
> 校验命令：`metal-doc gold validate --manifest goldset/v0/manifest.json`。

## 1. 目标

黄金集是**人工拥有的真值**，用于：

1. 判断模型/规则是否抽对（字段级、记录级）；
2. 判断是否抽全（覆盖、条款、检验项）；
3. 判断是否可发布（证据、幻觉、审核状态）。

铁律：**不得用模型输出或解析器输出反推标注**。标注必须回到源文档（OCR Markdown / 页图）逐项核对。

## 2. 标注粒度

| 粒度 | 对象 | 必填内容 |
|---|---|---|
| 单元格级 | 化学成分、力学性能表 | `raw`、`value`/`lower`/`upper`、`unit`、`comparator`、`evidence` |
| 记录级 | 表行 | `grade` 或 `grade_level`、`condition`、`facets`、`properties` |
| 检验项级 | 检验规则表 | 项目、各类别取样数量、取样部位、要求条款、试验方法 |
| 分类项级 | 牌号/状态表 | 牌号、旧牌号、状态、旧状态、含义 |
| 条款级 | 段落型字段 | 条款号、类型、字段（方法/方向/位置/数量/温度/判定）、证据 |

## 3. 文件格式

```json
{
  "schema_version": "0.1.0",
  "doc_id": "qdu302_2015",
  "standard_no": "Q/Du 302-2015",
  "doc_type": "enterprise",
  "source_type": "scanned",
  "annotation": {
    "status": "draft",
    "annotator": "agent-draft",
    "reviewers": [],
    "updated_at": "2026-10-25",
    "notes": []
  },
  "tables": [
    {
      "table_id": "T2",
      "page_no": 5,
      "profile": "mechanical_properties",
      "scope": "full",
      "records": [
        {
          "record_id": "qdu302-T2-2A14-切向",
          "grade": "2A14",
          "condition": "T6或T651或T652 / 切向",
          "facets": {"heat_treatment": "T6或T651或T652", "direction": "切向"},
          "properties": {
            "Rm": {
              "raw": "430",
              "value": 430.0,
              "unit": "MPa",
              "comparator": "min",
              "evidence": {
                "page_no": 5,
                "table_id": "T2",
                "row": 2,
                "col": 3,
                "quote": "430"
              }
            }
          }
        }
      ]
    }
  ],
  "clauses": []
}
```

完整字段定义见 `docs/schemas.md` 与 `metal_doc_agent/goldset.py`。

## 4. 字段规则

### 4.1 值

- `raw` 保留 OCR 原文（含 `≤`、`~`、数字间空格），不要“美化”。
- `value` 是规范数值；区间用 `lower/upper`；文本用 `text`。
- `unit` 从表头/条款取；百分比写 `%`；布氏硬度写 `HBW`（若源文为 `HB` 则写 `HB`）。
- `comparator` 按**要求方向**：
  - 表头/条款“不小于” → `min`，即使单元格只写数字；
  - “不大于” → `max`；
  - `a~b` → `range`；
  - `余量`、`提供实测数据` → `text`；
  - `-`、`不要求` → `na`（或直接不标注，视字段必填性）。
- 不得把 `≤0.015` 标成 `eq 0.015`。

### 4.2 记录身份

- `grade`：材料牌号（如 `2A14`、`2219`）；
- `grade_level`：质量/纯度级别（如 `普通级`、`优质级`）；
- `condition`：给人看的条件串；
- `facets`：机器匹配用，推荐键：
  `product_form`、`thickness`、`heat_treatment`、`specimen_state`、`direction`、`test_temperature`、`location`。
- 同一表内 `record_id` 唯一；建议 `{doc}-{table}-{grade}-{condition}`。

评测时记录键为 `(grade 或 grade_level, condition 的分面集合)`；空格、全半角、`*` 脚注会被忽略，但分面内容不会被模糊匹配。

### 4.3 证据

- 表格值：`page_no + table_id + row + col`（行列从 0 开始，对应 `TableGrid.rows`）。
- 条款值：`page_no + clause_id + quote`。
- `quote` 必须非空，且是源文中可检索的片段。
- 一个值一个证据；不要用整行/整表替代单元格证据。
- OCR 明显错位但语义可判定的单元格，先标 `annotation.status=draft`，并在 `note` 记录；不要静默修正。

### 4.4 表范围

- `scope=full`：整表已标注。评测时该表的多余预测会算 FP。
- `scope=partial`：只标注了部分行（如 GJB 2057A 表2 前 6 行）。评测时多余预测不计 FP，但未标注行的漏抽也不会被发现；`note` 必须写清未标注范围。

### 4.5 检验项

- `item`：检验项目（如 `化学成分`、`拉伸性能`）；
- `category`：分组（如 `力学性能`）；
- `quantities`：类别 → 数量；单列时用 `default`；
- `sample_location`：取样部位/方法；
- `requirement_clause`：要求章条号；
- `method_clause` / `method_standard`：试验方法章条号 / 标准号；
- `status=ambiguous`：OCR 或源文歧义，评测跳过该项，并在 `note` 说明。

### 4.6 条款字段

条款字段示例：

| 字段 | 含义 | 示例 |
|---|---|---|
| `sample_quantity` | 取样数量 | `9个`、`每批抽2件` |
| `sample_location` | 取样位置 | `上端面圆周` |
| `direction` | 方向 | `纵向`、`切向/径向/轴向` |
| `test_temperature` | 试验温度 | `室温`、`650℃` |
| `acceptance_level` | 合格级别 | `A级`、`I级或II级` |
| `test_method` | 试验方法 | `GB/T 228.1` |

条款 `kind` 取值：`scope`、`normative_reference`、`terms`、`technical_requirement`、`inspection`、`sampling`、`test_method`、`delivery`、`packaging`、`other`。

## 5. 歧义处理

按顺序选择：

1. 源文清楚 → 正常标注；
2. OCR 错位但可由上下文唯一恢复 → 标注 + `note` 记录恢复依据；
3. 无法唯一恢复 → `status=ambiguous` / 不进入评分，并记录 `note`；
4. 明确不适用 → `not_applicable`。

禁止：为了“让模型好看”而选择某个数值；禁止把 `-` 当成 0；禁止把区间端点猜成单值。

## 6. 双人流程与一致性

1. 标注员 A/B 独立标注同一文档（不同副本）；
2. 自动 diff：按 `(table_id, record_key, property)` 与 `(clause_id, field)` 比对；
3. 争议由领域专家仲裁，写入 `reviewers`；
4. 状态流转：`draft → reviewed → verified`；
5. 一致性门槛：
   - 单元格值完全一致 ≥98%；
   - `comparator + unit` 完全一致 ≥99%；
   - 条款字段完全一致 ≥95%；
   - 记录键一致率 ≥99%；
   - 争议项全部有仲裁记录。

未达门槛不得把黄金集用于 M1 退出评审。

## 7. 当前黄金集（20 份，verified）

| 文档 | 已标注表 | 记录/项 | 条款 | 已知缺口 |
|---|---|---|---|---|
| qdu302_2015 | T1 分类、T2 力学、T3 检验 | 3 分类 + 3 记录×5 值 + 7 检验项 | 5 | T4/T5 未标 |
| gbt40303_2021 | T3 化学、T9/T10 检验 | 3 记录（17/27/27 值）+ 16 检验项 | 5 | T4 力学表 OCR 行列错位，待 M1.5 |
| gjb2057a_2018 | T1 氢、T2 力学（partial）、T4 检验 | 1 记录×2 值 + 6 记录×4 值 + 11 检验项 | 6 | T2 仅前 6 行；T4 两项数量 ambiguous |
| gbt1591_2018 | T1 化学、T9 力学、T15 检验 | 11 记录 + 8 检验项 | 6 | C 厚度子列未拆 |
| gbt14992_2015 | T1/T2/T14 | 8 记录 + 5 分类项 | 4 | 源文页眉为 2005 版，需版次确认 |
| gbt3191_1998 | T6/T8 力学、T10 分类 | 10 记录 + 5 分类项 | 3 | T6 后段 OCR 空列 |
| gbt3191_2010 | T1 分类、T9 力学、T16 取样 | 8 记录 + 8 分类项 + 4 项 | 4 | 表11 检验项目未标 |
| gbt1220_2007 | T1 化学、T7 力学、T16 检验 | 11 记录 + 12 检验项 | 4 | 表6 表头 OCR 错位 |
| gbt33084_2016 | T1 化学、T5 力学、T12 检验 | 11 记录 + 8 检验项 | 3 | T1 部分列 OCR 噪声 |
| gbt3203_2016 | T4 化学、T8 力学、T15 检验 | 11 记录 + 8 检验项 | 4 | 表8 后段未标 |
| gbt3880_1_2012 | T13 化学、T17/T24 检验 | 5 记录 + 29 检验项 | 4 | T17/T24 只标部分 |
| gbt4437_1_2015 | T2 化学、T3 力学、T10 检验 | 12 记录 + 4 检验项 | 4 | T3 只标 5/23 行 |
| gbt6892_2015 | T3 化学、T4 力学、T19 检验 | 16 记录 + 1 检验项 | 4 | T4 只标 10 行；T19 仅 1 项 |
| gjb2294a_2014 | T1 化学、T5 力学、T15 检验 | 10 记录 + 10 检验项 | 4 | T1 “其他”列 OCR 错位 |
| gjb5301_2004 | T2 化学、T5 力学、T6 检验 | 9 记录 + 4 检验项 | 4 | T6 第4项跨页 |
| gjb3325a_2019 | T1 化学、T4 力学、T8 检验 | 6 记录 + 8 检验项 | 5 | T8 续页未标 |
| jx25_035 | T1 化学、T2 力学、T5 检验 | 2 记录 + 8 检验项 | 5 | T1 为元素行分块表 |
| mas7079_b | T7/T8 力学、T12 检验 | 4 记录 + 6 检验项 | 5 | 高温持久表未标 |
| qs10_0351_2004 | T2 化学、T3 力学、T5 检验 | 2 记录 + 6 检验项 | 4 | 表1 仅 1 行 |
| sjx100_410_2019 | T2 检验 | 7 检验项 | 4 | T2 实为理化检验表，无化学成分表 |

合计：20 份文档、60 张标注表、149 条记录、21 个分类项、157 个检验项、87 条条款；所有标注 `status=verified`。
`gold verify` 已校验 1595 条证据的页码/表/行列/quote；状态升级依据为自动化一致性复核 + 所有者覆盖，人工 A/B 双盲复核仍列为后续治理项。

## 8. 评测规则（与 `metal_doc_agent/eval/metrics.py` 对齐）

- 记录匹配：grade 相同且 condition token 集合互为子集（交集非空）；黄金集 condition 为空时接受同 grade 的预测 condition；
- 属性名先规范化：`KU1/KU2/KU5 → KV2`、`HBW → HB`；`A` 与 `A50mm` 保留为不同字段；
- 字段严格匹配：数值/文本正确 + `comparator` 正确 + `unit` 正确；
- `value_accuracy`：只看值，忽略 `comparator/unit`，分母是**已抽出的字段**，用于区分归一化错误和漏抽；
- 证据率：有 `evidence_id` 且该 id 存在于 `evidence.jsonl`；
- 幻觉率 = 1 − 证据率；
- 覆盖：必填项 `found` 或 `not_applicable` 计入覆盖；
- `scope=partial` 的表不计算多余预测 FP；
- `status=ambiguous` 的检验项/条款不进入分母。

## 9. 命令

```powershell
# 生成迷你集（序列化标注，不产生新事实）
python tools\build_mini_goldset.py

# 校验 manifest + 标注
python -m metal_doc_agent.cli gold validate --manifest goldset\v0\manifest.json

# 标注进度与证据校验
python -m metal_doc_agent.cli gold status --manifest goldset\v0\manifest.json
python -m metal_doc_agent.cli gold verify --manifest goldset\v0\manifest.json --runs runs\m1s7 --strict

# A/B 一致性
python -m metal_doc_agent.cli gold diff --a <A.json> --b <B.json> --out review.md --strict

# 跑基线并评测（含回归对比）
python -m metal_doc_agent.cli eval --gold goldset\v0 --runs runs\m1s7 --out eval\m1 `
  --baseline regression\v1.json --fail-on-regression
```

## 10. 版本与变更

- 标注文件必须带 `schema_version`；契约升级时同步迁移。
- 修改已发布标注：在 `annotation.notes` 记录原因、日期、人员；`verified` 状态变更需领域专家确认。
- 黄金集版本独立于代码版本；评测报告必须记录 `goldset_version + schema_version + model/prompt/recipe`。
