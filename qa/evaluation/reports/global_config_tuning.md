# 全局配置调优报告（结构化抽取）

- 文档：GJB3325A-2019（doc=427fcb66-87f0-4e9b-904f-e8dbeaf4b2ab）
- 时间：2026-08-14 11:04:07

| 配置 | 说明 | 状态 | 保留类别 | 记录数 | 剔除 | 字段填充率 | 完整率 | 可用率 | 脚本命中率 | 综合分 | 耗时(s) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| BASE | 当前默认（top_k=10, ctx=28k, 混合默认） | OK | 41 | 22 | 19 | 0.5547 | 0.0 | 0.6364 | 0.3636 | **0.4078** | 192.2 |
| CTX_SMALL | 小上下文（top_k=6, ctx=16k） | OK | 41 | 25 | 16 | 0.4153 | 0.04 | 0.52 | 0.32 | **0.3334** | 270.8 |
| CTX_LARGE | 大上下文（top_k=12, ctx=40k） | OK | 41 | 22 | 19 | 0.5219 | 0.0455 | 0.6364 | 0.2727 | **0.394** | 234.5 |
| KW_HEAVY | 词法权重高（kw=2.4, dense=0.8） | OK | 41 | 22 | 19 | 0.5255 | 0.0 | 0.6818 | 0.2727 | **0.3953** | 234.3 |
| DENSE_HEAVY | 语义权重高（kw=0.6, dense=1.6） | OK | 41 | 23 | 18 | 0.4808 | 0.0 | 0.5652 | 0.2174 | **0.3422** | 204.8 |
| STRICT | 严格召回（阈值0.035，无词法兜底） | OK | 24 | 11 | 13 | 0.5455 | 0.0 | 0.7273 | 0.4545 | **0.4409** | 120.6 |

综合分 = 0.35×字段填充率 + 0.25×完整率 + 0.25×可用率 + 0.15×脚本命中率

## LSAM-JD01-0016 验证（BASE vs STRICT）

| 配置 | 状态 | 保留类别 | 记录数 | 剔除 | 字段填充率 | 完整率 | 可用率 | 脚本命中率 | 综合分 | 耗时(s) |
|---|---|---|---|---|---|---|---|---|---|---|
| LSAM_BASE | OK | 41 | 24 | 17 | 0.75 | 0.2083 | 0.8333 | 0.4167 | **0.5854** | 180.9 |
| LSAM_STRICT | OK | 29 | 18 | 11 | 0.7477 | 0.2778 | 0.8333 | 0.5556 | **0.6228** | 135.6 |

## 结论与推荐配置

- 两份 test_doc 文档一致结论：**严格召回（category_recall.mode=strict，default_confidence_threshold=0.035，keyword_min_hits=999 关闭词法兜底）优于宽松模式**：
  - GJB3325A：STRICT 0.4409 vs BASE 0.4078（24/41 类别参与，耗时 120s vs 192s）；
  - LSAM-JD01-0016：STRICT 0.6228 vs BASE 0.5854（29/41 类别参与，耗时 135s vs 181s）；
- 上下文/混合权重：BASE（top_k=10、context_max_tokens=28000、混合默认）优于 CTX_SMALL/CTX_LARGE/KW_HEAVY/DENSE_HEAVY；
- 推荐写入 KB 的全局配置：retrieval.category_recall.mode=strict、default_confidence_threshold=0.035、keyword_min_hits=999（词法兜底关闭），其余检索参数保持默认；LLM 超时/并发按部署环境调整（调优时使用 timeout=600、并发 4~8 更稳定）。
- 注意：RRF 融合分整体在 0.03~0.05 区间，阈值需按文档集重新标定；词法兜底当前按“召回块是否命中 BM25”计数，区分度有限，后续可改为按命中 chunk 的 BM25 分数统计。


## 抽取引擎对比（BaseExtract vs LangExtract，GJB3325A-2019）

| 引擎 | 状态 | 记录数 | 剔除 | 字段填充率 | 完整率 | 可用率 | 脚本命中率 | 综合分 | 耗时(s) |
|---|---|---|---|---|---|---|---|---|---|
| BE_default | OK | 12 | 12 | 0.4966 | 0.0833 | 0.75 | 0.5 | **0.4571** | 116.8 |
| BE_batch | OK | 16 | 11 | 0.5076 | 0.0 | 0.6875 | 0.375 | **0.4058** | 130.7 |
| LE_default | OK | 19 | 12 | 0.6144 | 0.1579 | 0.7895 | 0.6842 | **0.5545** | 185.9 |
| LE_strong | OK | 18 | 12 | 0.5519 | 0.1111 | 0.8333 | 0.6111 | **0.5209** | 266.3 |

> 说明：当前两个引擎共用 llm_extractor.extract_category 同一实现，LangExtract 专属参数（passes/max_examples/fence_output/format_type/context_window_chars/max_char_buffer）未被消费，差异仅来自 LLM 输出随机性与并发参数。


## 抽取引擎对比（BaseExtract vs LangExtract，GJB3325A-2019）

| 引擎 | 状态 | 记录数 | 剔除 | 字段填充率 | 完整率 | 可用率 | 脚本命中率 | 综合分 | 耗时(s) |
|---|---|---|---|---|---|---|---|---|---|
| BE_default | OK | 16 | 11 | 0.5178 | 0.0 | 0.6875 | 0.375 | **0.4093** | 145.7 |
| BE_batch | OK | 14 | 12 | 0.5497 | 0.0 | 0.7143 | 0.3571 | **0.4245** | 130.6 |
| LE_default | OK | 18 | 11 | 0.5874 | 0.1667 | 0.7778 | 0.6667 | **0.5417** | 210.9 |
| LE_strong | OK | 21 | 11 | 0.5896 | 0.1429 | 0.8571 | 0.6667 | **0.5564** | 271.2 |
| LE_pkg_default | FAIL | - | - | - | - | - | - | - | - |
| LE_pkg_strong | FAIL | - | - | - | - | - | - | - | - |

> 说明：当前两个引擎共用 llm_extractor.extract_category 同一实现，LangExtract 专属参数（passes/max_examples/fence_output/format_type/context_window_chars/max_char_buffer）未被消费，差异仅来自 LLM 输出随机性与并发参数。


## 抽取引擎对比（BaseExtract vs LangExtract，GJB3325A-2019）

| 引擎 | 状态 | 记录数 | 剔除 | 字段填充率 | 完整率 | 可用率 | 脚本命中率 | 综合分 | 耗时(s) |
|---|---|---|---|---|---|---|---|---|---|
| BE_default | OK | None | None | None | None | None | None | **None** | None |
| BE_batch | OK | None | None | None | None | None | None | **None** | None |
| LE_default | OK | None | None | None | None | None | None | **None** | None |
| LE_strong | OK | None | None | None | None | None | None | **None** | None |
| LE_pkg_default | OK | 72 | 8 | 0.5438 | 0.1528 | 1.0 | 0.9861 | **0.6264** | 424.8 |
| LE_pkg_strong | OK | 43 | 6 | 0.7336 | 0.3023 | 0.907 | 0.9767 | **0.7056** | 296.3 |

> 说明：当前两个引擎共用 llm_extractor.extract_category 同一实现，LangExtract 专属参数（passes/max_examples/fence_output/format_type/context_window_chars/max_char_buffer）未被消费，差异仅来自 LLM 输出随机性与并发参数。
