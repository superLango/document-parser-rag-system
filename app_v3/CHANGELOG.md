# CHANGELOG

## [S11] 2026-11-25

### Added
- `scripts/s11_rebind.py`：WP1.0 全表重绑定试点（支持 `--docs` 限制文档数）
- `docs/S11-report.md`

### Results
- 试点 4 份小文档：gbt-8547 +2、gbt-2965/nbt 不变、xx454 -3
- 合计 211 匹配（S9 同文档 212）→ 不采用
- 失败原因：重绑定记录使用临时类别映射，未复用 v2 assemble

## [S10] 2026-11-25

### Added
- 后处理天花板评估；S11 转向决策
- `docs/S10-report.md`

## [S9] 2026-11-25

### Added
- 恢复通道度量标签修复
- `docs/S9-report.md`

### Results
- 6760/9724、0.7917、69.52%

## [S8] 2026-11-25

### Added
- 缺失列恢复、`全部牌号` 通配
- `docs/S8-report.md`

### Results
- 6745/9724、0.7930、69.36%

## [S7] 2026-11-25

### Added
- 牌号脚注清理
- `docs/S7-report.md`

## [S6] 2026-11-25

### Added
- DSL 执行器/回放/队列审计
- `docs/S6-report.md`

## [S5] 2026-11-25

### Added
- 证据感知冲突分级、TableIR、DSL 规范
- `docs/S5-report.md`

## [S4] 2026-11-25

### Added
- 数值 Grade/UNS、Grade 列推断、评测划分
- `docs/S4-report.md`

## [S3] 2026-11-25

### Added
- 条件补全、冲突分级
- `docs/S3-report.md`

## [S2] 2026-11-25

### Added
- 验证器、牌号修复、评测 matcher/run_eval
- `docs/S2-report.md`

## [S1] 2026-11-25

### Added
- schema/conditions/units/ontology、normalize、benchmark、eval、tests
