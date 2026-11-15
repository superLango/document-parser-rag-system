# 固定 Schema 驱动的修复方案（补充）

> 依据：旧项目 `configs/schema_templates/product_standard.json` 与 `metal_doc_agent/schema_projection.py`
> 结论：最终 Schema 固定不变，修复目标应从"记录数增加"改为"固定字段覆盖度提升"。

## 一、最终结构化 Schema（固定）

| 分类 | 字段 | 必填 |
|---|---|---|
| `standard_info` | 标准名称、标准编号 | 是 |
| `items[]` | 项目名称、材料牌号、标准要求 | 是 |
| `items[]` | 单位（数值型必填） | 条件必填 |
| `items[]` | 试验方法、试验温度、位置、方向、尺寸厚度、试样状态、取样数量、取样说明、锻件类型 | 条件必填（源文有则必须填） |
| `heat_treatment[]` | 材料牌号、工序名称、项目大类 | 是 |
| `heat_treatment[]` | 保温温度、保温时间、工艺名称、冷却介质、介质温度、装炉温度、出炉温度、升温速率、降温速率 | 条件必填（源文有则必须填） |

> "条件必填"不是可填可不填：源文出现该字段就必须填，源文确实没有才允许为空。

固定映射：`Rm→抗拉强度`、`Rp0.2→规定塑性延伸强度`、`ReH→屈服强度`、`A→断后伸长率`、`Z→断面收缩率`、`KV2→冲击吸收能量`、`HB/HRC/HV→布氏/洛氏/维氏硬度`；`化学成分/室温拉伸/高温拉伸/低温拉伸/夏比冲击/…` 为固定项目大类顺序。

## 二、把 Schema 变成修复 oracle

新增 `schema_contract.py`（固定常量）与 `coverage.py`（覆盖度计算）：

```python
SCHEMA = {
  "standard_info": {"required": ["标准名称", "标准编号"]},
  "items": {"required": ["项目名称", "材料牌号", "标准要求"],
            "optional": ["单位", "试验方法", "试验温度", "位置", "方向",
                          "尺寸厚度", "试样状态", "取样数量", "取样说明", "锻件类型"],
            "unit_required_when": "numeric"},
  "heat_treatment": {"required": ["材料牌号", "工序名称", "项目大类"],
                     "optional": ["保温温度", "保温时间", "工艺名称", "冷却介质",
                                   "介质温度", "装炉温度", "出炉温度", "升温速率", "降温速率"]},
}
```

`compute_coverage(records)` 输出：

- `required_total / required_present / required_rate`
- `complete_rows`（项目名称+材料牌号+标准要求 同时存在）
- `missing_fields`：`[{"field": "标准要求", "cause": "value_unparsed|no_column|unbound_column|row_skipped|not_in_source", "table_id", "row_index"}]`
- `optional_present`（试验方法/温度/方向等附加字段数量）

## 三、验收指标替换

| 规则 | 旧指标 | 新指标 |
|---|---|---|
| `DOC-NO-RECORDS` / `DOC-LOW-COVERAGE` | records > before | `complete_rows` 增加，或 `required_rate` 提升 |
| `DOC-UNBOUND-COLUMNS` | MEASURE_COLUMN_MISSING 下降 | `required_field:<name>` 的 present 数量增加（如 项目名称/材料牌号） |
| `DOC-DUP-KEYS` | 重复主键下降 | 不变 |
| `DOC-UNIT-MISSING` | 缺失单位比例下降 | `单位` 字段 present 率提升 |

门禁新增：`required_no_loss`（不得丢失任何已有必填字段）；可选字段增加只记为 `partial`，不单独判通过。

## 四、确定性决策树（先于模型补丁）

| 缺失字段 | 判定条件 | 修复级别 |
|---|---|---|
| 项目名称 | 有 measure 列但无项目名称 | L2 绑定 `项目名称` 映射（Rm→抗拉强度），不是修表 |
| 材料牌号 | 有牌号列但 row_key 未绑定 | L2 row_key |
| 材料牌号 | 无牌号列 / 表头合并 | L1 table_repair（header_rows / merge） |
| 标准要求 | 有要求列但值为空/未解析 | L1 patch_cells 或取值规则 |
| 标准要求 | 列不存在 | L1 table_repair 或标记 `not_in_source` |
| 单位 | 数值型但无单位 | L2 unit 配置 |
| 试验方法/温度/方向 | 表内无条件列 | 不修表，走条款/章节抽取或标记 `not_in_source` |

模型只在"表结构确需修复（合并表头、错列、行键缺失）"时生成 table_repair；其余交给配方绑定或规则修复，避免"用修表补丁掩盖绑定问题"。

## 五、回灌与重试

上一轮失败时，除 checks 外必须回灌：

- `coverage_before` / `coverage_after` 的差分（哪个必填字段没补上）
- `missing_fields` 及 cause
- `ROW_SKIPPED` 的行号与原因（无牌号/全空/脚注/列数不足）
- 目标表可用的列候选（表头 → 固定字段的候选映射）

## 六、对 6 次 rollback 的映射

| 案例 | 缺失必填字段 | 应走路径 |
|---|---|---|
| T5 / T1 / T7 `DOC-NO-RECORDS` | 材料牌号或标准要求 | 先查 row_key/项目名称绑定；确实缺列才 L1 |
| T8 `DOC-UNBOUND-COLUMNS` | 项目名称（measure 列存在） | L2 绑定 measure→项目名称，禁止改数据单元格 |
| L2 `DOC-LOW-COVERAGE` | 必填覆盖未变，仅值变化 | 标记 `partial`，不判通过；或按 rule 降级为取值修复 |
| T22 `DOC-LOW-COVERAGE` | 必填覆盖增加 | 已通过（语义删除判定修复） |

## 七、实施顺序

1. `schema_contract.py` + `coverage.py` + 单测（用旧模板字段作为固定断言）
2. RepairContext 注入 `schema` / `coverage` / `missing_fields` / `column_candidates`
3. 验收指标切换 + 门禁 `required_no_loss`
4. 行级诊断（`ROW_SKIPPED` 带 row_index/reason）与重试回灌
5. 确定性决策树接入，限制模型只处理"表结构确需修复"的场景
6. 13 条真实反馈复测，按 `required_rate` / `complete_rows` 评估

预期：这能直接解释并减少当前 6 次 `target_metric` rollback——因为模型会拿到"缺哪个必填字段、为什么缺"，而不是只知道"记录数没涨"。
