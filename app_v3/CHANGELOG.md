# CHANGELOG

## [S10] 2026-11-25

### Added
- `docs/S10-report.md`：后处理天花板评估
- `eval/s10-collapse-test-eval.json`：选择性替换实验（不采用）
- `eval/s10-syn-eval.json`：高倍同义词实验（无变化）

### Findings
- 后处理层已接近天花板：条件/牌号/名称归一到位后，增量规则收益趋近 0
- S9 仍为最佳：6760/9724、0.7917、69.52%
- 决策：S11 转"全表重绑定 + 条款通道 + 盲测"，停止后处理增量修补

## [S9] 2026-11-25

### Added
- `channels/table_recover.py`：度量标签修复（跳过条件段/脚注）
- `tests/test_table_recover.py` 更新
- `docs/S9-report.md`

### Results
- 恢复记录 36 条
- 修正 matcher 后：6760/9724、0.7917、69.52%（较 S8 +15）
- 测试：52 passed

## [S8] 2026-11-25

### Added
- `channels/table_recover.py`：缺失度量列恢复
- `eval/matcher.py`：`全部牌号` 通配
- `scripts/s8_demo.py`、tests
- `docs/S8-report.md`

### Results
- 修正 matcher 后：6745/9724、0.7930、69.36%
- 同口径原始 v2：6713/9724、69.04%
- 测试：52 passed

## [S7] 2026-11-25

### Added
- `analyze/grade_cleanup.py`、`scripts/s7_demo.py`、tests、报告

### Results
- 清理牌号 1083 条；评测 6700/9724、0.7943、68.90%
- 测试：49 passed

## [S6] 2026-11-25

### Added
- DSL 执行器/回放/队列审计/盲测占位

### Results
- gbt-2054 T9：209 条，回放 coverage=1.0；评测 6698/9724、0.7944、68.88%
- 测试：47 passed

## [S5] 2026-11-25

### Added
- 证据感知冲突分级、TableIR、DSL 规范

### Results
- unresolved 1370→820；评测 6698/9724、0.7944、68.88%
- 测试：43 passed

## [S4] 2026-11-25

### Added
- 数值 Grade/UNS、Grade 列推断、评测划分

### Results
- 牌号解析率 85.65%→91.67%；评测 6698/9724、0.7944、68.88%
- 测试：39 passed

## [S3] 2026-11-25

### Added
- 条件补全、冲突分级

### Results
- unresolved 1544→1370；评测 6698/9724、0.7952、68.88%
- 测试：36 passed

## [S2] 2026-11-25

### Added
- 验证器、牌号修复、评测 matcher/run_eval

### Results
- 校准 6672/9724、0.7899、68.61%
- 保守修复 6698/9724、0.7890、68.88%
- 测试：34 passed

## [S1] 2026-11-25

### Added
- schema/conditions/units/ontology、normalize、benchmark、eval、tests

### Notes
- 未修改冻结版 v2 代码。
