# CHANGELOG

## [S3] 2026-11-25

### Added
- nalyze/condition_repair.py：从表标题/表头路径/行键补全温度、状态、尺寸、方向
- erify/conflicts.py：冲突分级（条件不足时 alue_conflict_insufficient_conditions warn）
- scripts/s3_demo.py：条件补全 + 验证演示
- 	ests/test_condition_repair.py
- docs/S3-report.md

### Results
- 条件修复记录 2281 条；verify unresolved 1544→1370，队列 2356→2161
- 评测：6698/9724，一致率 0.7952（+0.62pp），覆盖率 68.88%

## [S2] 2026-11-25

### Added
- `analyze/grade_columns.py`：表格牌号列分析
- `analyze/document_grade.py`：文档级牌号推断
- `analyze/repair.py`：牌号修复（默认保守模式）
- `verify/evidence.py`：证据验证
- `verify/conservation.py`：值守恒验证
- `verify/conditions.py`：条件完整性验证
- `verify/conflicts.py`：冲突检测
- `verify/queue.py`：未解决队列
- `verify/pipeline.py`：验证流水线 CLI
- `eval/matcher.py`：冻结 v5 matcher 迁入
- `eval/run_eval.py`：固定评测入口
- `scripts/s2_demo.py`：S2 修复+验证演示
- `tests/test_analyze.py`、`tests/test_verify.py`
- `docs/S2-report.md`

### Results
- 评测器校准：6672/9724、0.7899、68.61%（与冻结基线一致）
- 保守牌号修复：6698/9724、0.7890、68.88%（ISO 0→26）
- 验证器：9185 条，ok 6829 / warn 812 / unresolved 1544，队列 2356

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
