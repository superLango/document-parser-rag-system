# V3 抽取前流程梳理（2026-08-29, 以 V3 为最新流程）

> 完整链路: 文档索引 → 类别展开 → 证据判定 → 三路检索 → 重排 → 过滤 → 上下文组装 → 送入 LLM。
> 本文档说明各阶段产出的**块数**与管线连接。

## 0. 总览

```
文档(已索引) document_chunks
   │
   ├─ ① 类别展开       build_targets          → 41 个类别(term_base 展开)
   ├─ ② 证据判定       build_one_v2 前置      → 每个类别: 保留/剔除
   │     (always / 字面任意 / 语义≥0.60 / 关键词)
   ├─ ③ 类别召回       retrieval_service.search(1) → 25 块(每维候选40)
   ├─ ④ 数据路检索     retrieval_service.search(2) → 40 块(每维候选160)
   ├─ ⑤ 元信息路检索   retrieval_service.search(3) → 20 块(每维候选80)
   ├─ ⑥ 合并去重       data+meta              → ≤60 块
   ├─ ⑦ 类别级过滤     重排分数阈值(≥-5)      → 60 块(几乎全保留)
   ├─ ⑧ 上下文组装     assemble_*             → 40 块(修正后)
   └─ ⑨ LLM 抽取       prompt 拼装            → 单次拼接发送
```

## 1. 配置来源（关键）

| 阶段 | 配置来源 | top_k | context_top_k | per_dim | candidate_mult |
|---|---|---|---|---|---|
| 检索(③④⑤) | `LARGE_CANDIDATES`(V3 override) | 40 | 60 | 40 | 4 |
| 上下文组装(⑧) | V3 配置(全局+LARGE_CANDIDATES) | **40** | 60 | — | — |

**（原不一致已修正, 见 §4）**: 现上下文组装与检索同用 V3 配置 → 检索 60 块, 送 LLM 40 块。

## 2. 各阶段块数明细

### ① 类别展开（category_builder.build_targets）
- Schema 模板 "产品标准抽取模板" → 3 个类别:
  - 热处理制度(always)、标准信息(always)、term_base 展开类别(39 个 feature)
- 合计 **41 个类别**(每个类别独立走 ③-⑨)

### ② 证据判定（build_one_v2, V3）
对每个类别:
- always(标准信息/热处理制度): 无条件保留
- 非 always: `字面任意命中` OR `语义≥0.60(表格块)` OR `关键词命中(≥0.50)` → 保留
- 无证据 → `SkippedFeature`(剔除, 不进入检索/LLM)

### ③ 类别召回（第一路, 判断类别是否存在）
`retrieval_service.search(top_k=25, per_dim_top_k=40)`
- title 路候选 40 + content 路候选 40(各取 top 40)
- BM25 词法路候选 40
- dense 融合 → RRF(60, dense 1.0 / kw 1.2) → 返回 **25 块**

### ④ 数据路检索（第二路, 数据结构表）
`retrieval_service.search(top_k=40, candidate_mult=4)`
- title/content 各取 **160**(40×4), BM25 160
- RRF 融合 → 返回 **40 块**

### ⑤ 元信息路检索（第三路, 元信息块）
`retrieval_service.search(top_k=20)`
- title/content 各取 **80**(20×4), BM25 80
- RRF → 返回 **20 块**

### ⑥ 合并去重（build_one_v2）
- data(40) + meta(20) → `merged_hits.setdefault`(数据路优先) → **≤60 块**

### ⑦ 类别级过滤（重排分数阈值）
- KB `reranker.enabled=true`(CrossEncoder bge-reranker-v2-m3), `threshold=-5.0`(V3 override)
- 非 always: `max_rerank ≥ -5.0` → 保留(几乎全保留, 负 logits 放宽)
- always: 无条件保留

### ⑧ 上下文组装（pipeline._extract_single, 2026-08-29 已修正）
- `ctx_top_k = min(top_k=40, context_top_k=60) = 40`（V3 配置, 已修正被全局 15 截断问题）
- `assemble_page_order(hits, top_k=40)`(页码序) 或 `assemble_full_sorted`(重排序, 0 条时重试)
- **送 LLM 块数 = 40**(修正后; 检索 60 块中按页码/重排取前 40)

### ⑨ LLM 抽取
- 单段 `segments=[{type: text, content: ctx}]`
- BaseExtract(默认) 或 LangExtractPkg; 整段一次给模型

## 3. 最终块数汇总

| 环节 | 块数 |
|---|---|
| 每类别检索候选(合并后) | ≤60 |
| 送 LLM 上下文块 | **40**(min(top_k=40, context_top_k=60)) |
| 41 类别 × 40 块 | 最多 1640 块入 Prompt(实际按类别分别发送, 每类 40 块) |

## 4. ✅ 已修正（2026-08-29）

**原问题**: 检索 k40(60 块) 但送 LLM 仅 15 块 — 候选放大收益被上下文截断抵消。
**修正**: pipeline route=v3 时, `_extract_single` 使用 V3 配置
(`{**全局retrieval, **LARGE_CANDIDATES}`), 即 ctx_top_k = min(40, 60) = **40**;
检索 60 块中按页码/重排取前 40 送 LLM。
**`docs/RETRIEVAL_RECALL_OPTIMIZATION_PLAN.md` 同步此结论。**

---

## 5. V3 检索耗时与瓶颈(2026-08-29 实测)

### 5.1 稳态耗时(41 类,单文档 GB-T1220)

| 配置 | 单类 | 41 类 | 说明 |
|---|---|---|---|
| 未优化(3 路各自 rerank) | ~15s | ~600s | ❌ 3 次 search 各做 CrossEncoder 重排 |
| **3 路 skip_rerank + 合并重排 1 次** | **~5.1s** | **210s** | ✅ 当前 V3 |
| 去掉合并重排 | ~2.7s | ~110s | 损失精排质量(召回不变,排序差) |

### 5.2 瓶颈分布(5.1s/类)

| 环节 | 耗时 |
|---|---|
| 证据判定(字面+语义) | ~0.5s |
| 3 路检索(ANN+BM25, skip_rerank) | ~0.06s |
| **合并重排(CrossEncoder 15 候选, 内容~1500字符)** | **~2-3s** |
| 其他(query 构建/组装) | ~1.5s |

### 5.3 已做的优化(2026-08-29)

1. `retrieval_service.search` 加 `skip_rerank` 参数;
2. `build_one_v2` 3 路检索 skip_rerank=True, 合并后只重排一次(top_n=15);
3. rerank 候选从 40→15(实测 25 候选 3.4s→15 候选 2-3s);
4. 语义证据批量/共享矩阵(单类 ~0.5s, 批量 0.07s 已实现但 build_one_v2 仍逐类);

### 5.4 剩余优化空间(待决策)

- **A. 语义证据批量接入 build_one_v2**(把 41 类的 evidence 判定一次批量算): 省 ~30s;
- **B. 去掉合并重排**(页码序上下文, 阈值-5 几乎不剔): 省 ~100s → 110s;
- **C. sort_mode=rerank**(用重排分排序, 质量更高但耗时不减);
- **D. 类别级并发**(实测 1.0x, GPU 瓶颈无效)。

**建议**: 保留合并重排(质量优先, 210s 是 arq 后台任务可接受); 后续如需提速选 B(重排只影响排序, 召回 0.946 不变)。
