# LangExtractPkg GH4169 抽取验证（块级过滤关闭）

- 文档：LSAM-JD01-0016 GH4169.pdf（doc=92f5b301-b65d-4415-a925-94f3d29c704a，loose 召回）
- 配置：engine=LangExtractPkg；max_tokens=8192；max_char_buffer=3000；context_window_chars=500；passes=2；batch_length=8；max_workers=8
- 时间：2026-08-20 00:15:03

## 本次结果

| 记录数 | 剔除 | 拼接字段命中 | 完整率 | 可用率 | 脚本命中率 | 综合分 | 溯源记录率 | 耗时(s) |
|---|---|---|---|---|---|---|---|---|
| 32 | 26 | 54 | 0.0312 | 0.0625 | 0.8438 | **0.3813** | 0.094 | 271.1 |

## 与上一版（分段多次调用原包）对比

未找到上一版指标文件 gb1220_segmented/gb1220seg_LEpkg_metrics.json，跳过对比。

文件说明：run.json 完整结果（记录含 _evidence 溯源）；run_simple.json 简化视图；metrics.json 指标。