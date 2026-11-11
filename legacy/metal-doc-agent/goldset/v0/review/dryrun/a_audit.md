# A 标注独立审计（dry-run）

> 依据 TableGrid 表头 comparator、原始值与证据 locator 对 A 做规则审计；不修改 A。

| 文档 | 表 | 记录 | 字段 | 原因 | A 值/evidence |
|---|---|---|---|---|---|
| gbt1220_2007 | T7 | gbt1220_2007-T7-022Cr19Ni10N-固溶处理 | Z | comparator_header_mismatch | {"comparator": "min", "expected": "max", "header": "硬度b 不大于"} |
| gbt1220_2007 | T7 | gbt1220_2007-T7-10Cr18Ni12-固溶处理 | Z | comparator_header_mismatch | {"comparator": "min", "expected": "max", "header": "硬度b 不大于"} |
| gbt1220_2007 | T7 | gbt1220_2007-T7-06Cr25Ni20-固溶处理 | Z | comparator_header_mismatch | {"comparator": "min", "expected": "max", "header": "硬度b 不大于"} |
| gbt1220_2007 | T7 | gbt1220_2007-T7-06Cr17Ni12Mo2-固溶处理 | Z | comparator_header_mismatch | {"comparator": "min", "expected": "max", "header": "硬度b 不大于"} |
| gbt1220_2007 | T7 | gbt1220_2007-T7-022Cr17Ni12Mo2-固溶处理 | Z | comparator_header_mismatch | {"comparator": "min", "expected": "max", "header": "硬度b 不大于"} |

## 原因统计

| 原因 | 数量 |
|---|---|
| comparator_header_mismatch | 5 |
