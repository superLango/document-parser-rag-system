# CHANGELOG

## [S14] 2026-11-25

### Added
- `scripts/s14_router_all.py`：S13 路由应用到 20 份冻结文档
- `channels/router.py`：覆盖代理阈值 1.05→1.15（修正 asme 误路由）
- `docs/S14-report.md`

### Results
- 路由 20 份：6795/9724、0.7923、69.88%（S9：6760/0.7917/69.52%）
- +35 匹配、+0.36pp 覆盖率；多余 2461→2657
- G1 未通过（覆盖率<72%、一致率<0.80、多余>2000）
- 测试：56 passed

## [S13] 2026-11-25

### Added
- `channels/router.py`（覆盖代理路由）
- `scripts/s13_router.py`、`tests/test_router.py`
- `docs/S13-report.md`

### Results
- 6 份冻结文档：1190→1219（+35），覆盖率 56.05%
- 路由：gbt-8547/hb/gbt-2965/astm 全链路；xx454/gbt-3620 S9

## [S12] 2026-11-25

### Added
- `scripts/s12_full_pipeline.py`
- `docs/S12-report.md`

### Results
- 3 份试点：gbt-8547 +3、hb +6、xx454 -3；合计 139/287

## [S11] 2026-11-25

### Added
- `scripts/s11_rebind.py`
- `docs/S11-report.md`

### Results
- 4 份小文档：211（S9 同文档 212）→ 不采用

## [S10] 2026-11-25

### Added
- `docs/S10-report.md`（后处理天花板）

## [S9] 2026-11-25

### Results
- 6760/9724、0.7917、69.52%

## [S8] 2026-11-25

### Results
- 6745/9724、0.7930、69.36%

## [S7] 2026-11-25

### Results
- 6700/9724、0.7943、68.90%

## [S6] 2026-11-25

### Results
- 6698/9724、0.7944、68.88%

## [S5] 2026-11-25

### Results
- 6698/9724、0.7944、68.88%

## [S4] 2026-11-25

### Results
- 6698/9724、0.7944、68.88%

## [S3] 2026-11-25

### Results
- 6698/9724、0.7952、68.88%

## [S2] 2026-11-25

### Results
- 6698/9724、0.7890、68.88%

## [S1] 2026-11-25

### Added
- schema/conditions/units/ontology、normalize、benchmark、eval、tests
