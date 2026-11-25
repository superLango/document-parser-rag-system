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
