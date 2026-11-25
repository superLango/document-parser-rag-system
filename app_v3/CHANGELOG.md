# CHANGELOG

## [S6] 2026-11-25

### Added
- `table_program/engine.py`：DSL 执行器（explode/melt/pivot/filter）
- `table_program/replay.py`：回放校验（值覆盖/缺失/多余）
- `verify/audit.py`：未解决队列审计
- `scripts/s6_audit.py`、`scripts/s6_dsl_demo.py`
- `tests/test_table_program.py`
- `eval/blind_manifest.json`：盲测清单占位
- `docs/S6-report.md`、`docs/S6-audit.md`

### Results
- 真实表 gbt-2054 T9：DSL 产出 209 条，回放 coverage=1.0
- 队列审计：2161 条；missing_temperature 1323、value_conflict 820、same_row 558
- 评测与 S5 一致：6698/9724、0.7944、68.88%
- 测试：47 passed

## [S5] 2026-11-25

### Added
- `verify/conflicts.py`：证据感知冲突分级
- `table_program/ir.py`：表格 IR v1
- `table_program/DSL.md`：DSL v1 规范（草案）
- `scripts/s5_demo.py`
- `tests/test_table_ir.py`；更新 `tests/test_verify.py`
- `docs/S5-report.md`

### Results
- verify unresolved 1370→820（同表同行冲突 558 降为 warn）
- 评测与 S4 一致：6698/9724、0.7944、68.88%
- 测试：43 passed

## [S4] 2026-11-25

### Added
- `normalize/grade.py`：数值 Grade 与 UNS 牌号归一
- `analyze/grade_columns.py`：Grade 列推断
- `scripts/s4_demo.py`、`tests/test_s4_grade_columns.py`
- `eval/splits.json`
- `docs/S4-report.md`

### Results
- 牌号解析率 85.65%→91.67%，grade_rejected 1319→766
- 评测：6698/9724、0.7944、68.88%
- 测试：39 passed

## [S3] 2026-11-25

### Added
- `analyze/condition_repair.py`
- `verify/conflicts.py` 分级
- `scripts/s3_demo.py`、`tests/test_condition_repair.py`
- `docs/S3-report.md`

### Results
- 条件修复 2281 条；unresolved 1544→1370，队列 2356→2161
- 评测：6698/9724、0.7952、68.88%
- 测试：36 passed

## [S2] 2026-11-25

### Added
- 验证器（证据/守恒/条件/冲突/队列）
- 牌号列分析/文档级牌号/保守修复
- 固定评测 matcher + run_eval
- `scripts/s2_demo.py`、tests
- `docs/S2-report.md`

### Results
- 评测器校准：6672/9724、0.7899、68.61%
- 保守修复：6698/9724、0.7890、68.88%
- 测试：34 passed

## [S1] 2026-11-25

### Added
- schema/conditions/units/ontology
- normalize（items/grade/conditions/aliases/pipeline/report）
- benchmark（26 docs + gold + manifest）
- eval baseline、scripts/s1_demo.py
- tests（24）

### Notes
- 未修改冻结版 v2 代码；
- S1 只做归一化与诊断，上游绑定错误的修复在 S2。
