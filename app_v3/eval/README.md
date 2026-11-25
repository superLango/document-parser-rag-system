# app_v3 评估数据

## 内容

- `baseline-v2-metrics.json`：冻结版 v2 的 20 份文档指标（覆盖率/一致率/时间）
- `baseline-v2-categories.json`：冻结版 v2 的分类别缺口
- `s1-normalization-report.json`：S1 归一化层在 20 份 v2 产物上的统计
- `s2-baseline-eval.json`：评测器对基线的回放（6672/9724、0.7899、68.61%）
- `s2-repaired-eval.json`：S2 保守牌号修复后的评测（6698/9724、0.7890、68.88%）
- `s2-repair-verify-report.json`：S2 修复+验证汇总
- `s3-eval.json`：S3 条件补全后的评测（6698/9724、0.7952、68.88%）
- `s3-repair-verify-report.json`：S3 修复+验证汇总
- `s4-eval.json`：S4 牌号修复后的评测（6698/9724、0.7944、68.88%）
- `s12-full-eval.json`：S12 冻结文档全链路试点（gbt-8547/xx454/hb-20079，139/287）
- `s11-pilot-eval.json` / `s11-selected4-eval.json`：S11 全表重绑定试点（4 份小文档，不采用）
- `s10-collapse-test-eval.json`：S10 选择性替换实验（不采用，6752/69.44%）
- `s10-syn-eval.json`：S10 同义词实验（无变化，6760/69.52%）
- `s9-eval.json`：S9 结果（6760/9724、0.7917、69.52%）
- `s8-eval.json`：S8 结果（6745/9724、0.7930、69.36%）
- `s8-wild-raw-baseline.json`：原始 v2 + 修正 matcher 的同口径基线（6713/9724、69.04%）
- `s8-recover-report.json`：S8 恢复+验证汇总
- `s7-eval.json`：S7 牌号脚注清理后的评测（6700/9724、0.7943、68.90%）
- `s7-grade-cleanup-report.json`：S7 清理+验证汇总
- `s7-temp-default-eval.json` / `s7-recover-test-eval.json` / `s7-recover-strict-eval.json`：S7 负向/探索实验
- `s6-audit.json`：S6 未解决队列审计（原因/类别/文档分布）
- `s6-dsl-demo.json`：S6 DSL 真实表执行/回放结果（gbt-2054 T9，coverage=1.0）
- `blind_manifest.json`：真正盲测清单（待新增未见文档）
- `s5-verification-report.json`：S5 证据感知冲突分级后的验证汇总（unresolved 820）
- `s4-repair-verify-report.json`：S4 修复+验证汇总
- `s4-normalization-report.json`：S4 后牌号解析率（91.67%）
- `splits.json`：回归 20 份 / 历史 holdout 6 份划分
- `run_eval.py`（在 `eval/run_eval.py`）：固定评测入口

## 评测口径（固定）

- 匹配：类别 + 项目名归一 + 牌号 + 温度/状态 + 值数值集合
- 一致率 = 值一致 / 匹配
- 覆盖率 = 匹配 / 金标
- 多余率 = 多余 / 我方记录
- 未解决率 = unresolved / 金标

## 原则

- gold 只用于评测，不参与规则/词表推导；
- 固定 20 份 + 盲测集；
- 每次改动输出分类别报告与回归对比；
- 评测入口：`python -m app_v3.eval.run_eval`。
