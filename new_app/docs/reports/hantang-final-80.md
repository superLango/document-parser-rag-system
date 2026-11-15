# 汉唐标准全量解析基线

> 生成时间：2026-11-15T06:50:37.840504+00:00
> 服务：http://localhost:18000；并发：4
> 样本：80 份（跳过 >25MB 大文件 0 份）

## 1. 汇总

| 指标 | 结果 |
|---|---|
| 结构化成功 | 23/80 |
| 失败 | 57 |
| 记录数 | 7891 |
| 字段数 | 24455 |
| 零记录文档 | 0（0.00%） |
| 审核发现数 | 1454（涉及 76 份） |
| p50 / p95 耗时 | 52.73s / 627.94s |
| 批次总耗时 | 12084.36s |

## 2. 分类别

| 类别 | 文档 | 结构化成功 | 记录 | 字段 | 零记录 | 耗时(s) |
|---|---|---|---|---|---|---|
| 美国标准 | 11 | 10 | 349 | 1006 | 0 | 703 |
| 国家标准 | 51 | 1 | 7109 | 22196 | 0 | 10119 |
| 企业标准 | 3 | 2 | 3 | 13 | 0 | 118 |
| 国军标 | 7 | 4 | 304 | 818 | 0 | 445 |
| 行业标准 | 6 | 4 | 84 | 296 | 0 | 176 |
| 国际标准 | 2 | 2 | 42 | 126 | 0 | 522 |

## 3. 策略与诊断

| 策略 | 命中文档数 |
|---|---|
| grade_property_matrix | 1 |
| property_rows | 6 |

| 诊断码 | 次数 |
|---|---|
| DOCUMENT_GRADE_FALLBACK | 10 |
| DOCUMENT_INTELLIGENCE_APPLIED | 69 |
| DOCUMENT_METADATA_APPLIED | 69 |
| DUPLICATE_KEY_DISAMBIGUATED | 386 |
| DUPLICATE_KEY_DISAMBIGUATED_SUMMARY | 30 |
| DUPLICATE_RECORDS_REMOVED | 12 |
| DUPLICATE_TABLE | 1 |
| ELEMENT_COLUMNS_NOT_FOUND | 10 |
| EMPTY_RECORD_SKIPPED | 1989 |
| ENGINE_ASSETS | 69 |
| FRAGMENT_RECORDS_MERGED | 11 |
| GRADE_SPLIT | 163 |
| HEAT_TREATMENT_DERIVED | 1 |
| MEASURE_COLUMN_MISSING | 11986 |
| MERGED_GRADE_FILLED | 16 |
| NONRECORD_TABLE | 335 |
| NO_RECORDS | 122 |
| PARSER_BUNDLE | 69 |
| ROW_KEY_NOT_FOUND | 73 |
| ROW_KEY_PLACEHOLDER | 2 |
| ROW_SKIPPED | 524 |
| STRATEGY_BLOCKED | 11 |
| STRATEGY_HIT | 8 |
| STRATEGY_MISS | 232 |
| UNROUTED_TABLE | 3980 |
| VALUE_OUT_OF_RANGE | 575 |

## 4. 零记录文档明细

| 文档 | 类别 | 页 | 表 | 状态 |
|---|---|---|---|---|
