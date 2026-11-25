# CHANGELOG

## [S8] 2026-11-25

### Added
- `channels/table_recover.py`：缺失度量列恢复（按 record_id 列号只补缺失列）
- `eval/matcher.py`：`全部牌号/所有牌号/各牌号/任意牌号/通用` 通配语义
- `scripts/s8_demo.py`
- `tests/test_table_recover.py`、`tests/test_matcher.py`
- `docs/S8-report.md`

### Results
- 恢复记录 71 条
- 修正 matcher 后：S8 6745/9724、一致率 0.7930、覆盖率 69.36%
- 同口径原始 v2 基线：6713/9724、0.7886、69.04%
- 测试：52 passed

## [S7] 2026-11-25

### Added
- `analyze/grade_cleanup.py`：牌号脚注清理
- `scripts/s7_demo.py`、`tests/test_grade_cleanup.py`
- `docs/S7-report.md`

### Results
- 清理牌号 1083 条
- 评测：6700/9724、0.7943、68.90%
- 负向实验：类别室温默认无变化；跳过表恢复宽松 +3/+65 多余、严格 0 条
- 测试：49 passed

## [S6] 2026-11-25

### Added
- DSL 执行器/回放校验/队列审计/盲测占位
- `docs/S6-report.md`、`docs/S6-audit.md`

### Results
- gbt-2054 T9：209 条，回放 coverage=1.0
- 队列 2161；评测 6698/9724、0.7944、68.88%
- 测试：47 passed

## [S5] 2026-11-25

### Added
- 证据感知冲突分级、TableIR v1、DSL 规范
- `docs/S5-report.md`

### Results
- unresolved 1370→820
- 评测 6698/9724、0.7944、68.88%
- 测试：43 passed

## [S4] 2026-11-25

### Added
- 数值 Grade/UNS、Grade 列推断、表格牌号修复、评测划分
- `docs/S4-report.md`

### Results
- 牌号解析率 85.65%→91.67%
- 评测 6698/9724、0.7944、68.88%
- 测试：39 passed

## [S3] 2026-11-25

### Added
- 条件补全、冲突分级
- `docs/S3-report.md`

### Results
- unresolved 1544→1370；评测 6698/9724、0.7952、68.88%
- 测试：36 passed

## [S2] 2026-11-25

### Added
- 验证器、牌号修复、评测 matcher/run_eval
- `docs/S2-report.md`

### Results
- 评测器校准 6672/9724、0.7899、68.61%
- 保守修复 6698/9724、0.7890、68.88%
- 测试：34 passed

## [S1] 2026-11-25

### Added
- schema/conditions/units/ontology、normalize、benchmark、eval、tests

### Notes
- 未修改冻结版 v2 代码。
