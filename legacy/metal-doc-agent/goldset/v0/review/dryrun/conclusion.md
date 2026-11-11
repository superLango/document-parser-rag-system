# WS1 AI 独立复核 dry-run 结论

- 日期：2026-10-26
- 方法：以 `runs/m1_qwen_s8` 生成 B 草案（仅 chemical/mechanical 记录），与 A（当前 verified 标注）做 diff；同时对 A 做表头 comparator、数值解析、证据 locator 的规则审计。
- 性质：**dry-run，不作为 verified 依据，不移除 `owner-override`**；人工 A/B 双盲复核仍需执行。

## 1. 结果概览

- B 草案：20 份，`goldset/v0/review/dryrun/b/`。
- A/B diff：20 份，`goldset/v0/review/dryrun/reports/`。
- A 审计：36 个初始标记 → 规则去噪后 **5 个**，全部集中在 `gbt1220_2007` T7 的 `Z` 字段。
- 结论：**未发现 A 的确定性转写错误**；5 个标记均可解释为 TableGrid 表头缺失，不是 A 标注错误。

## 2. A 审计 5 个标记的解释

| 文档 | 表 | 字段 | 原因 | 结论 |
|---|---|---|---|---|
| gbt1220_2007 | T7 | Z | 表头“硬度b 不大于”，A comparator=min | T7 原始表头缺少 `断面收缩率Z/%` 列；数据行第 7 列实际是 Z，A 证据 col7、值 50、min 均正确 |

原始 HTML 证据：T7 表头为 `断后伸长率A/%` 后直接 `硬度b colspan=3`，但数据行在 A 后有一个 Z 值，随后才是 HBW/HRB/HV 三个硬度值。TableGrid 把 Z 列误标为硬度列，属于表头缺陷，不是 A 错误。

其余初始标记均已排除：

- `unit_header_mismatch`：`N/mm²`、`Mpa`、`J/cm²`、`HB(d)` 等被 `parse_unit` 误拆；A 单位正确。
- `comparator_header_mismatch`：`≤16` 厚度子表头被误判为 comparator；O 状态行 `≤205/≤125` 与通用“不小于”表头冲突，A 按原始符号记 max 正确。
- `evidence_quote_mismatch`：`gbt4437` T2 的 `0.30~0.9Bi0.35~1.2Sn` 是 OCR 合并单元格，A quote 是完整单元格的子串；A 语义正确。
- `value_parse_mismatch`：`jx25` 的 `341-293HB(...)` 是降序硬度区间；A 用 lower=293/upper=341 正确。

## 3. B diff 的主要差异

B 只覆盖 chemical/mechanical 记录，且 A 为 partial scope，因此 record_key agreement 普遍偏低；在共同记录键上，value agreement 多数为 1.0 或较高：

| 文档 | record_key | value | strict | 说明 |
|---|---|---|---|---|
| qdu302_2015 | 1.0 | 1.0 | 1.0 | 一致 |
| gbt40303_2021 | 1.0 | 0.8625 | 0.8625 | B 少量列/值差异 |
| gbt3880_1_2012 | 1.0 | 0.6885 | 0.6885 | B 缺 `其他杂质`、`Co` 等特殊字段；A 省略了 B 的 `-` 字段 |
| gjb3325a_2019 | 1.0 | 0.9556 | 0.9556 | KIC/单位差异已基本收敛 |
| mas7079_b | 1.0 | 1.0 | 1.0 | 一致 |
| gbt1591_2018 | 0.1364 | 1.0 | 1.0 | B 记录多、A partial；共同键值一致 |
| gbt3191_2010 | 0.3478 | 1.0 | 1.0 | B 记录多、A partial；共同键值一致 |
| gbt3191_1998 | 0.0 | 1.0 | 1.0 | A/B 条件/记录集合不交叠；需人工复核 |

B 的缺口与 WS2 一致：`inspection_items`、`classification_items`、`clauses` 均为空；特殊字段（其他元素、杂质合计、KIC/KU 等）覆盖不足。

## 4. 结论与建议

1. **A 标注可信度**：规则审计未发现确定性错误；5 个标记是 TableGrid 表头缺陷。A 可继续保持 verified，但仍需人工 A/B。
2. **B 草案不能替代人工 B**：B 来自被评测模型，存在循环偏差；仅用于差异排查。
3. **治理状态**：`owner-override` 保留；人工 A/B 与仲裁完成前不改标注状态。
4. **后续动作**：
   - 将 `gbt1220_2007` T7 的 Z 表头缺失加入 TableGrid/困难表修复清单；
   - 人工 B 标注使用 `goldset/v0/review/b/` 空模板，独立填写；
   - 人工仲裁后运行 `tools/gold_review_batch.py`，四个一致性指标达门槛再移除 `owner-override`；
   - WS2 优先补 inspection/classification/clause 与特殊字段，减少 B 草案缺口。

## 5. 产物

- 汇总：`goldset/v0/review/dryrun/summary.md`
- A 审计：`goldset/v0/review/dryrun/a_audit.md`
- B 草案：`goldset/v0/review/dryrun/b/`
- 逐文档 diff：`goldset/v0/review/dryrun/reports/`
