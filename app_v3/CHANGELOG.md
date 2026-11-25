# CHANGELOG

## [S7] 2026-11-25

### Added
- `analyze/grade_cleanup.py`：牌号脚注清理（`BZn9-29f → BZn9-29`）
- `scripts/s7_demo.py`：S7 清理+验证演示
- `tests/test_grade_cleanup.py`
- `docs/S7-report.md`

### Results
- 清理牌号 1083 条
- 评测：6700/9724、一致率 0.7943、覆盖率 68.90%（+2 匹配）
- 负向实验：类别室温默认无变化；跳过表恢复宽松 +3/+65 多余、严格 0 条
- 测试：49 passed

## [S6] 2026-11-25

### Added
- `table_program/engine.py`：DSL 执行器（explode/melt/pivot/filter）
- `table_program/replay.py`：回放校验
- `verify/audit.py`：未解决队列审计
- `scripts/s6_audit.py`、`scripts/s6_dsl_demo.py`
- `tests/test_table_program.py`
- `eval/blind_manifest.json`
- `docs/S6-report.md`、`docs/S6-audit.md`

### Results
- 真实表 gbt-2054 T9：209 条，回放 coverage=1.0
- 队列 2161；missing_temperature 1323、value_conflict 820
- 评测：6698/9724、0.7944、68.88%
- 测试：47 passed

## [S5] 2026-11-25

### Added
- `verify/conflicts.py`：证据感知冲突分级
- `table_program/ir.py`：TableIR v1
- `table_program/DSL.md`：DSL v1 规范
- `scripts/s5_demo.py`
- `tests/test_table_ir.py`；更新 `tests/test_verify.py`
- `docs/S5-report.md`

### Results
- unresolved 1370→820；same-row 558 降级
- 评测：6698/9724、0.7944、68.88%
- 测试：43 passed

## [S4] 2026-11-25

### Added
- `normalize/grade.py`：数值 Grade 与 UNS 归一
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
