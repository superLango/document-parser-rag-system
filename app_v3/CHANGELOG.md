# CHANGELOG

## [S12] 2026-11-25

### Added
- `scripts/s12_full_pipeline.py`：冻结口径文档全链路重绑定试点
- `docs/S12-report.md`

### Results
- 3 份冻结文档试点：gbt-8547 +3、hb-20079 +6、xx454 -3
- 全链路合计 139/287（48.4%），S9 同文档 133（46.3%）
- 结论：缺表文档有效；需按文档路由（S13）

## [S11] 2026-11-25

### Added
- `scripts/s11_rebind.py`：全表重绑定试点（支持 --docs 限制）
- `docs/S11-report.md`

### Results
- 4 份小文档试点：合计 211（S9 同文档 212）→ 不采用；失败原因：临时类别映射

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
