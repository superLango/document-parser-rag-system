# CHANGELOG

## [S16] 2026-11-26

### Added
- `channels/llm_client.py`：OpenAI-compatible LLM 客户端
- `channels/instruction_table_schema.txt`：原生表格列描述 prompt
- `channels/table_schema_channel.py`：模型列描述 + 代码展开
- `scripts/s16_native.py`：原生通道试点
- `tests/test_table_schema_channel.py`
- `docs/S16-report.md`

### Results
- 3 份试点：原生单独 1261 匹配、一致率 0.9667
- 原生+S9：3543/4561（77.68%），一致率 0.8100，多余 3740
- 相对 S9 同文档 +103 匹配、覆盖率 +2.26pp；多余不达标
- 测试：57 passed

## [S15] 2026-11-25

### Results
- v2 全链路上限 ≈69.9%；决定原生重做

## [S14] 2026-11-25

### Results
- 20 份路由：6795/9724、0.7923、69.88%

## [S13] 2026-11-25

### Results
- 6 份路由 +35；覆盖代理路由

## [S12] 2026-11-25

### Results
- 3 份全链路试点：139/287

## [S11] 2026-11-25

### Results
- 4 份重绑定试点不采用

## [S10] 2026-11-25

### Added
- 后处理天花板评估

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
