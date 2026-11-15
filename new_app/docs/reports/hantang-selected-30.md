# 汉唐标准全量解析基线

> 生成时间：2026-11-15T06:48:41+00:00
> 服务：http://localhost:18000；并发：4
> 样本：30 份（跳过 >25MB 大文件 0 份）

## 1. 汇总

| 指标 | 结果 |
|---|---|
| 结构化成功 | 23/30 |
| 失败 | 7 |
| 记录数 | 836 |
| 字段数 | 2493 |
| 零记录文档 | 0（0.00%） |
| 审核发现数 | 355（涉及 28 份） |
| p50 / p95 耗时 | 60.85s / 1797.46s |
| 批次总耗时 | 434.64s |

## 2. 分类别

| 类别 | 文档 | 结构化成功 | 记录 | 字段 | 零记录 | 耗时(s) |
|---|---|---|---|---|---|---|
| 企业标准 | 3 | 2 | 3 | 13 | 0 | 504 |
| 国军标 | 7 | 4 | 304 | 818 | 0 | 7914 |
| 国家标准 | 1 | 1 | 54 | 234 | 0 | 0 |
| 国际标准 | 2 | 2 | 42 | 126 | 0 | 226 |
| 美国标准 | 11 | 10 | 349 | 1006 | 0 | 755 |
| 行业标准 | 6 | 4 | 84 | 296 | 0 | 544 |

## 3. 策略与诊断

无策略命中。

| 诊断码 | 次数 |
|---|---|
| DOCUMENT_GRADE_FALLBACK | 6 |
| DOCUMENT_INTELLIGENCE_APPLIED | 21 |
| DOCUMENT_METADATA_APPLIED | 21 |
| DUPLICATE_KEY_DISAMBIGUATED | 12 |
| DUPLICATE_KEY_DISAMBIGUATED_SUMMARY | 5 |
| DUPLICATE_RECORDS_REMOVED | 2 |
| ELEMENT_COLUMNS_NOT_FOUND | 1 |
| EMPTY_RECORD_SKIPPED | 139 |
| ENGINE_ASSETS | 21 |
| FRAGMENT_RECORDS_MERGED | 2 |
| HEAT_TREATMENT_DERIVED | 1 |
| MEASURE_COLUMN_MISSING | 1428 |
| NONRECORD_TABLE | 59 |
| NO_RECORDS | 20 |
| PARSER_BUNDLE | 21 |
| ROW_KEY_NOT_FOUND | 17 |
| ROW_SKIPPED | 56 |
| STRATEGY_BLOCKED | 1 |
| STRATEGY_MISS | 24 |
| UNROUTED_TABLE | 549 |
| VALUE_OUT_OF_RANGE | 4 |

## 4. 零记录文档明细

| 文档 | 类别 | 页 | 表 | 状态 |
|---|---|---|---|---|
