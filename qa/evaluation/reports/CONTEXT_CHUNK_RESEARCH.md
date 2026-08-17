# 检索块 → 上下文组装 大小研究（防 LLM 上下文超限）

> 对象：GB-T1220-2007（doc=09a79bb1…），模型 Qwen3.6-35B-A3B-FP8 max_model_len=55000。
> 结论：块本身不大，超限根因是“max_tokens 输出预算过大 + 上下文预算按字符估算偏乐观”，不是检索块过大。

## 1. 检索块（document_chunks）尺寸

- 总块数：83（含 29 个表格块）
- content 字符数：min=1，avg=820，p50=113，p95=3691，max=4427
- 折算 token（按 1.3 字符/token）：avg≈631，p95≈2839，max≈3405
- 表格块：avg 2064 字符（≈1588 token），max 4427 字符（≈3405 token）

## 2. 上下文组装推演（top_k=10，context_max_tokens=28000）

- 预算字符 = 28000 × 1.5 = 42000 字符
- 最坏 top10 块合计 34602 字符 ≈ 26616 token（仍在预算内）
- 单次请求总 token ≈ 上下文 26616 + 模板 1500 + 输出 8192 ≈ 36308 < 55000 ✅
- 若输出 max_tokens=32768：26616 + 1500 + 32768 ≈ 60884 > 55000 ❌（即此前 400 根因：提示词 22233 + 输出 32768 = 55001）

## 3. 防超限规则（代码已实现 input_char_budget）

输入字符预算 = (55000 - max_tokens - 3000) × chars_per_token
- max_tokens=8192 → 输入预算 ≈ 65712 字符
- BaseExtract 分批 batch_chars=6000 字符/次；LangExtractPkg 窗口=20000 字符/次
- 结论：max_tokens ≤ 8192 且 context_max_tokens ≤ 28000 时不会超限（实测无 400）

## 4. 推荐配置

- retrieval.top_k=10，context_top_k=20，context_max_tokens=28000
- llm.max_tokens=8192，timeout=600
- BaseExtract：batch 8000/6000/500/32000
- LangExtractPkg：passes=2，examples=3，window=20000，buffer=30000

## 5. 并发与稳定性观察（2026-08-17）

- 并发 2：LangExtractPkg loose 517s 完成；BaseExtract loose 曾因 max_tokens=4096 截断失败
- 并发 8：不再出现 400（超限已解决），但 GB-T1220 上极慢/不稳定：
  BaseExtract 多次在 40% 事件循环空转挂起；LangExtractPkg 35 分钟仍卡 40%
- 建议：当前 vLLM（max-num-seqs=8、大输出长生成）下生产并发建议 2-4；
  并发 8 需在 vLLM 侧调优或限制输出长度后再评估
