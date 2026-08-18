# LangExtractPkg 引擎收敛专项验证（官方特性全开）

- 文档：GB-T1220-2007 不锈钢棒.pdf（doc=09a79bb1-1c17-44bc-bb02-57eab2e25580，loose 召回）
- 配置：engine=LangExtractPkg；max_tokens=8192；max_char_buffer=3000；context_window_chars=500；passes=2；batch_length=8；max_workers=8
- 时间：2026-08-18 17:46:07

## 本次结果

| 记录数 | 剔除 | 拼接字段命中 | 完整率 | 可用率 | 脚本命中率 | 综合分 | 溯源记录率 | 耗时(s) |
|---|---|---|---|---|---|---|---|---|
| 163 | 9 | 60 | 0.0061 | 0.9755 | 0.9202 | **0.5375** | 1.0 | 1994.6 |

## 与上一版（分段多次调用原包）对比

未找到上一版指标文件 gb1220_segmented/gb1220seg_LEpkg_metrics.json，跳过对比。

文件说明：run.json 完整结果（记录含 _evidence 溯源）；run_simple.json 简化视图；metrics.json 指标。