# CHANGELOG

## [S1] 2026-11-25

### Added
- `schema/record.v1.schema.json`：规范记录 JSON Schema
- `schema/conditions.v1.json`、`schema/units.v1.json`：条件/单位规范
- `schema/ontology.v1.json`：类别/项目本体（76 类 / 1070 项 / 1158 方法）
- `normalize/items.cn_en.json`：中英项目/度量词表
- `normalize/grade.py`：牌号解析（中英/多牌号/纯字母/表头短语拒绝/别名）
- `normalize/conditions.py`：状态/方向/温度/尺寸/单位归一
- `normalize/aliases.py`：文档内状态别名挖掘
- `normalize/pipeline.py`：归一化流水线 + CLI + summary
- `normalize/report.py`：报告输出
- `benchmark/`：26 份基准 PDF + gold + `manifest.json`（PDF 本地备份，gold/manifest 入库）
- `eval/`：v2 基线快照 + S1 归一化报告
- `scripts/s1_demo.py`：S1 演示脚本
- `tests/`：24 个单元测试

### Notes
- 未修改冻结版 v2 代码；
- S1 只做归一化与诊断，上游绑定错误的修复在 S2。
