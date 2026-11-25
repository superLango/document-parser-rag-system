# 表格程序 DSL v1（草案）

> 阶段：P1 WP1.1  
> 目标：模型输出"表格变换程序"，确定性引擎执行；执行后**回放重建**表格，逐单元格校验，不一致则拒绝/重试。

## 1. 程序结构

```json
{
  "schema_version": "table_program.v1",
  "table_id": "T9",
  "header_rows": 2,
  "key_columns": [0, 1, 2],
  "steps": [
    {"op": "explode", "column": 0, "delimiter": "[、,，]"},
    {"op": "melt",
     "id_columns": [0, 1, 2],
     "value_columns": [
        {"column": 3, "measure": "抗拉强度(Rm)", "unit": "MPa", "operator": null,
         "conditions": {"试验温度": "室温"}}
     ]},
    {"op": "normalize", "fields": {"条件.尺寸厚度": "size_mm", "牌号": "grade"}},
    {"op": "filter", "where": "value not in ['-', '', '—']"}
  ],
  "postconditions": {"preserve_all_cells": true}
}
```

## 2. 操作符（v1）

| op | 参数 | 语义 |
|---|---|---|
| `explode` | `column`, `delimiter` | 拆分多值单元格（多牌号/多状态） |
| `melt` | `id_columns`, `value_columns` | 宽表 → 长表；value_columns 指定 measure/unit/operator/conditions |
| `pivot` | `index`, `columns`, `values` | 长表 → 宽表（转置表） |
| `rename` | `mapping` | 列名/度量名重命名 |
| `normalize` | `fields` | 牌号/条件/单位归一（调用 app_v3.normalize） |
| `filter` | `where` | 过滤脚注/空值 |
| `merge_conditions` | `from_columns` | 行键条件合并（状态/尺寸/温度） |
| `expand_grades` | `column` | 多牌号展开 |

## 3. 校验（必须）

1. **值守恒**：melt 后所有非空 value cell 都必须生成一条记录（除 filter 显式排除）；
2. **回放**：用记录反向重建表格，与原表逐单元格比对（允许显式 ignored cells）；
3. **条件完整**：melt 的每个 value_column 必须带必要条件；
4. **失败处理**：回放失败 → 标记 `program_rejected`，降级到结构化通道/双通道/人工。

## 4. 示例（化学宽表）

```json
{"schema_version":"table_program.v1","table_id":"T2","header_rows":1,
 "key_columns":[0,1],
 "steps":[
   {"op":"melt","id_columns":[0,1],
    "value_columns":[{"column":2,"measure":"C","unit":"%","operator":"≤"},
                     {"column":3,"measure":"Si","unit":"%","operator":"≤"}]}
 ]}
```

## 5. 示例（转置牌号表）

```json
{"schema_version":"table_program.v1","table_id":"T30","header_rows":2,
 "key_columns":[0],
 "steps":[
   {"op":"pivot","index":[0,1],"columns":2,"values":[3,4,5,6],
    "value_columns":[{"column":3,"measure":"抗拉强度(Rm)","unit":"MPa"}]}
 ]}
```

## 6. 与 P0 的关系

- P0 的归一化/验证器作为 `normalize` 步骤与 `postconditions` 被 DSL 复用；
- P1 先用程序模板覆盖化学宽表/热处理/冲击/硬度，再逐步扩展。
