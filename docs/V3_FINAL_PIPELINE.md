# V3 抽取前流程最终定稿（2026-08-29）

> 已确定：以「V3 最新逻辑」为 BaseExtract 链路与一站式抽取链路的统一流程。
> 后续如需调整再议。

## 1. 一、总体流程图

```
文档(已索引, document_chunks)
   │
   ① 类别展开          build_targets             → 41 类别(标准信息/热处理制度 always + term_base 展开)
   │
   ② 证据判定(V3):
        always               → 无条件保留
        字面任意命中          → 保留
        语义≥0.60(表格块)    → 保留
        语义≥0.50+类别核心词  → 保留
        皆无                  → SkippedFeature(剔除, 不检索不抽取)
   │
   ③ 类别召回(第一路)   search(top_k=25, per_dim=40, skip_rerank)  → RRF top25
   ④ 数据路检索(第二路) search(top_k=40, 每维160, skip_rerank)      → RRF top40
   ⑤ 元信息路检索(第三路) search(top_k=20, 每维80, skip_rerank)    → RRF top20
   │
   ⑥ 合并去重            data(40)+meta(20) → ≤60 块
   ⑦ 上下文组装         (无重排) ctx_top_k=min(top_k=40, context_top_k=50)=40 → 40 块
   │
   ⑧ LLM(BaseExtract)   整段拼接一次给模型(输出80000, 输入预算48000, chars_per_token=1.0)
```

## 2. 配置(KB=25e7d8ef)

| 项 | 值 |
|---|---|
| retrieval.route | **v3**(pipeline 默认 v3, 仅显式 v1 回退旧链路) |
| top_k / candidate_mult | 40 / 4 |
| category_recall | {mode: loose, top_k: 25, per_dim_top_k: 40} |
| data_route_top_k / meta_route_top_k | 40 / 20 |
| context_top_k | 50(实际 ctx_top_k=min(40,50)=40) |
| reranker | enabled=true(model 保留), **threshold=-5**, block_filter=false, sort_mode=page(默认) |
| 合并重排 | **关闭**(3 路 skip_rerank, 合并后不精排) |
| llm.engine | BaseExtract, max_tokens=80000 |
| context_max_tokens | 48000 |
| chars_per_token | 1.0 |

## 3. 两路检索分工(实测)

| 类别 | 数据路(术语集) | 元信息路(fixed_query) | 合并 |
|---|---|---|---|
| 化学成分 | 40(表格22) | 20(表格2) | 47 |
| 室温拉伸 | 40(表格29) | 20(表格3) | 50 |
| 热处理制度 | 40(表格24) | 20(表格11) | 43 |

- 数据路主管**数据表**(22-29 表格块), 元信息路主管**正文元信息**(方法/取样/项目表)。

## 4. 回归数据(35 文档, 最新逻辑)

| 指标 | 值 |
|---|---|
| 文档数 | 35(sha256 去重) |
| 类别实例 | 194 |
| **全数召回(recall=1.0)** | **189 / 0.974** |
| **平均召回** | **0.994** |
| 跳过 | 0 |
| 未全数(5) | 均超大多表(need 8-26): NPS-CFR600 热处理 0.875 / PR02-MTS01E 0.933 / JSXY 热处理 0.875 / NWS3100 化学成分 0.808 / NWS3100 热处理 0.278 — hits 40-54 已全候选, 目标块数超 ctx_top_k, 极值场景 |

## 5. 耗时(单文档, 稳态实测)

| 阶段 | 耗时 |
|---|---|
| OCR 解析 | ~16.7s |
| 索引 | ~2.5s |
| 类别召回/证据判定/剔除(41 类) | **~91s**(2.23s/类) |
| 送入 LLM 前合计 | **~110s** |

## 6. 两链路接线(保证)

```
BaseExtract 链路: run_extraction_task → pipeline.run(engine=BaseExtract)
                    → route=v3 → build_one_v2 → _extract_single → llm_extractor
一站式链路:      integration/upload → arq OCR → 索引 → _trigger_integration_extract
                    → extract_document_task → run_extraction_task → pipeline.run(同上)
```
- 两条链路共用同 pipeline.run / build_one_v2;
- KB route='v3'(已设), pipeline 默认 route='v3'(已改), 仅显式 route='v1' 回退旧链路;
- 重排器模型/代码保留(注释注明), 默认不调用。

## 7. 本版改进点(相对 V1/早期 V3)

1. 证据判定(字面+语义0.60+关键词0.50) → 零误剔(跳过0);
2. 术语全保留(不限量, 文档感知精选), 解决 C↔碳/蠕变↔持久 漏剔;
3. 3 路检索 skip_rerank + 完整 top_k(40/20/25) → 候选 43-60, 修复 reranker_top_n 截断退化;
4. 合并无重排 → 省 ~100s(210s→91s), 召回 0.994 保持;
5. 语义证据批量/共享矩阵(0.07s/批);
6. BaseExtract 输出 80000 / 输入预算 48000 / chars_per_token 1.0。
