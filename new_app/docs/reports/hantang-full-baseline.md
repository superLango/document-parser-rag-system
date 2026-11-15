# 汉唐标准全量解析基线

> 生成时间：2026-11-12T19:16:23+00:00
> 服务：http://localhost:18000；并发：4
> 样本：185 份（跳过 >25MB 大文件 4 份）

## 1. 汇总

| 指标 | 结果 |
|---|---|
| 结构化成功 | 151/185 |
| 失败 | 34 |
| 记录数 | 6955 |
| 字段数 | 24344 |
| 零记录文档 | 1（0.66%） |
| 审核发现数 | 6748（涉及 150 份） |
| p50 / p95 耗时 | 165.46s / 779.73s |
| 批次总耗时 | 11620.35s |

## 2. 分类别

| 类别 | 文档 | 结构化成功 | 记录 | 字段 | 零记录 | 耗时(s) |
|---|---|---|---|---|---|---|
| 国家标准 | 54 | 39 | 3950 | 14175 | 1 | 14424 |
| 国际标准 | 3 | 3 | 50 | 143 | 0 | 0 |
| 国军标 | 32 | 28 | 1166 | 4489 | 0 | 15684 |
| 企业标准 | 3 | 3 | 56 | 216 | 0 | 900 |
| 美国标准 | 82 | 71 | 1570 | 4751 | 0 | 11889 |
| 行业标准 | 11 | 7 | 163 | 570 | 0 | 2222 |

## 3. 策略与诊断

| 策略 | 命中文档数 |
|---|---|
| grade_property_matrix | 4 |
| hardness_minmax | 2 |
| property_matrix | 1 |

| 诊断码 | 次数 |
|---|---|
| DUPLICATE_TABLE | 176 |
| ELEMENT_COLUMNS_NOT_FOUND | 257 |
| EMPTY_RECORD_SKIPPED | 4898 |
| ENGINE_ASSETS | 151 |
| GRADE_SPLIT | 124 |
| MEASURE_COLUMN_MISSING | 47752 |
| NONRECORD_TABLE | 1015 |
| NO_RECORDS | 5334 |
| PARSER_BUNDLE | 150 |
| RECIPE_FALLBACK | 5729 |
| ROW_KEY_NOT_FOUND | 4490 |
| ROW_KEY_PLACEHOLDER | 82 |
| ROW_SKIPPED | 11692 |
| STRATEGY_BLOCKED | 152 |
| STRATEGY_HIT | 17 |
| STRATEGY_MISS | 23962 |

## 4. 零记录文档明细

| 文档 | 类别 | 页 | 表 | 状态 |
|---|---|---|---|---|
| GBT 16598-1996过期.pdf | 国家标准 | - | 0 | STRUCTURED_READY |

## 5. 跳过大文件（>25MB）

- GJB 8268-2014 航空用沉淀硬化不锈钢棒规范.pdf
- AMS4928W-过期.pdf
- YB 4069-91.pdf
- YYT 0345.1-2020.pdf
