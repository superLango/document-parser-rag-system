# Chunk 大小与「送模型不截断/不超限」方案调研（2026-08）

> 目标：对照市面上成熟方案，梳理「入库分块大小」与「抽取上下文组装→送模型」两段的
> chunk 尺寸设定、上下文预算计算、超长切分与防超限策略，找出本系统差距与改进点。

## 1. 本系统现状（代码级）

### 1.1 入库分块（`backend/app/services/indexing/chunker.py`）

- 子块上限 `MAX_CHILD_CHARS = 2000` 字符（注释：BGE-M3 max_length=8192 留余量；表格增强文本计入）；
- overlap `MAX_OVERLAP_CHARS = 200` 字符 / `MAX_OVERLAP_SENTENCES = 2` 句，overlap 处插入 `[--上下文接续--]`；
- 层级父子分块：父块=完整章节（parent_text），组内按段落/句子边界切子块，**禁止句子内截断**；
- 表格独立成块、不切分。

### 1.2 抽取上下文组装（`pipeline.py` → `context_assembler.py`）

- 检索 top_k 默认 10、context_top_k 默认 20（全局配置 `extraction_config_service.py`）；
- `assemble(..., max_tokens=None)`：**不按预算截断**，全部命中块按相关性顺序拼接（带页码前缀）。

### 1.3 BaseExtract（`llm_extractor.py`）

- `MODEL_CONTEXT_WINDOW_TOKENS = 55000` **硬编码**（注释：Qwen3.6-35B-A3B-FP8 max_model_len=55000）；
- `_INPUT_RESERVE_TOKENS = 3000`（输出预留）；
- `input_char_budget = (55000 - max_tokens - 3000) × chars_per_token(1.5)`；
- `extract_category` 仍先按 `context_truncate = min(32000, input_budget)` **截断上下文**（旧逻辑残留）；
- `_extract_base`：≤ single_threshold(8000 字符) 单次请求；否则 `split_context`（batch_chars=6000、overlap=500 字符）按**纯字符窗口**切段，逐段独立请求，结果按 JSON 全等去重；任一段失败整体失败。

### 1.4 LangExtractPkg（`lang_pkg_extractor.py`，原包 1.6.0）

- 复用同一 `split_context`（batch_chars=6000、overlap=500、input_budget）；
- 传原包时 `context_window_chars=None`、`max_char_buffer=len(seg)`：即**由我们预切段，禁用原包自身分块/上下文窗口**；
- 每段独立 `lx.extract`（passes 默认配置 2），段级 600s 超时，结果 JSON 全等去重。

### 1.5 已知问题点（本次调研前已存在）

1. `55000` 窗口与 `1.5 字符/token` 均为硬编码估算，未与模型资源配置联动，也未用模型 tokenizer 精确计数；中文约 1.5-2 字符/token，英文约 4 字符/token，估算偏差大。
2. `max_tokens` 全局默认 32768 过大：输出预算挤占输入（55000-32768-3000≈19k token 输入），且单类别实际输出远小于 32768，浪费上下文。
3. BaseExtract 的 `context_truncate=32000` 与「不截断」目标**自相矛盾**：上下文在分段前已被截断，超限部分直接丢失。
4. `split_context` 纯字符窗口切分，**不尊重句子/段落/版面块边界**，可能把同一表格/条款拆到两段；overlap 是裸字符，模型无法区分「这是上一段上下文」。
5. LLM 客户端（`llm_client.py`）对 400 错误**不做分类**：context over limit 与其它错误同样报错，无「自动缩小该段重试」兜底。

## 2. 市面方案

### 2.1 LangExtract（我们已用原包）官方策略

- **智能分块**：`ChunkIterator` 优先保持句子完整（Case A 多句打包到 ≤ max_char_buffer）、新行处断开（结构化文本）、单 token 超长独立成块；`max_char_buffer` 默认 **1000 字符**（原包签名确认）。
- **推荐档位**：高精度 500-1500 字符；平衡 1500-2500；高召回 2500-4000；成本优化 4000-6000。
- **context_window_chars**：把上一 chunk 尾部指定字符拼到当前 chunk 开头（示例 `max_char_buffer=2000, context_window_chars=500`），解决代词/跨块实体；代价为 token 成本 +10-30%。
- **多轮抽取**：`extraction_passes>1` 全量重抽，结果按**字符区间重叠合并（first-pass wins）**，非简单 JSON 去重。
- **并行**：`batch_length × max_workers`，有效并行度=min(batch, workers)。

### 2.2 LlamaIndex

- `SimpleNodeParser` 默认 chunk_size=**1024 token**、overlap=**20 token**；社区最佳实践 chunk_size 512-2048，overlap 为 chunk 的 **10-20%**；`SentenceSplitter` 建议 overlap ≥ 50 token 处理自然语言。

### 2.3 LangChain

- `RecursiveCharacterTextSplitter` 默认 chunk_size=**1000 字符**、chunk_overlap=**200 字符**；按分隔符递归切（段落→句子→词），不跨词截断；`from_tiktoken_encoder` 可切到精确 token 数。

### 2.4 LightRAG

- 默认 `chunk_token_size=1200` token、overlap **100 token**（环境变量 CHUNK_SIZE=1200）；按 tokenizer 精确窗口切分；另有 semantic chunker（不强制上限）。

### 2.5 RAGFlow

- General 模板默认 **512 token**，后端硬上限 **2048 token**（用户配置超限会被钳制）；另有按文档类型预设的模板（论文/书籍/法律等）按结构切。

### 2.6 Unstructured

- 元素化后按策略分块，全部受 **max characters 硬上限**约束：
  - by_character：hard limit + soft limit（new-after-n）+ overlap（默认仅用于超长元素，overlap all 才用于所有块）；超大元素按空格/换行切词，**大表格按行切为 TableChunk**；
  - by_title：以标题为节边界，单块不跨节；combine-text-under-n 合并小节；
  - by_page：单块不跨页；
  - by_similarity：embedding 相似度 ≥ 阈值才同块；
  - 可选 **contextual chunking**（Anthropic 思路）：为每块前置「块级说明」上下文。

### 2.7 vLLM / OpenAI 上下文管理实践

- 预算公式主流做法：**输入预算 = max_model_len − max_tokens(输出) − 保留 token（2000-4000）**；我们 reserve 3000 符合区间，但窗口/字符比应来自模型实际配置与 tokenizer；
- vLLM 对超限请求**直接返回 400，不做钳制**（issue #42474：max_tokens 是硬要求而非上限）；请求前必须精确预估输入+输出 ≤ max_model_len；
- 通用实践：系统提示精简、目标输出长度写入 prompt 并用 max_tokens 兜底、动态上下文修剪/压缩（Redis 上下文溢出实践）。

### 2.8 商业 IDP（Azure / Textract）

- 抽取模型按页/表格粒度处理，天然规避单请求超限：Azure 支持 pages 参数与 2000 页上限；Textract 异步每页最多 30 个 Query；长文档靠分页/异步/分块输出拼接。

### 2.9 批量抽取工程实践（MLJAR 等）

- 长文档重叠分块独立抽取；**合并时按字段取「信号最清晰」的 chunk 值**，而非全等去重；跨块依赖是并行分块的已知弱点（BMR 论文实测）。

## 3. 与本系统对照表

| 维度 | 本系统 | 市面主流 | 结论 |
|---|---|---|---|
| 入库子块大小 | 2000 字符（约 1000-1300 token） | RAGFlow 512-2048 token、LightRAG 1200、LlamaIndex 1024 | 同级，无需改 |
| 入库切分边界 | 段落/句子边界、表格独立 | 同；Unstructured 额外支持页边界/语义相似 | 一致；可补「页边界」选项 |
| 抽取片段大小 | batch_chars=6000 字符（纯字符窗口） | LangExtract 建议 1000-4000；其切分尊重句子/新行 | **偏大且切分粗糙**：应语义边界切分 |
| 上下文预算 | (55000−max_tokens−3000)×1.5 字符，窗口硬编码 | 精确 tokenizer 计数 + 模型真实窗口 + 输出预留 2000-4000 | **估算误差大、窗口不联动模型配置** |
| 输出预留 | 3000 token | 2000-4000 token | 符合 |
| 防截断 | BaseExtract 残留 context_truncate=32000；Pkg 全量分段 | 不截断或按预算压缩（Retrieval 截断属于方案差异） | **Base 残留截断需清除** |
| 超长切分 | split_context 字符窗口 + 500 字符 overlap | LangExtract sentence-aware + context_window 语义拼接 | 应改语义边界 + 标记上下文来源 |
| 合并策略 | JSON 全等去重 | LangExtract 区间重叠 first-pass wins；MLJAR 按字段择优 | 应升级为按主键/字段择优 |
| 超限兜底 | 400 即整体失败 | vLLM 前置精确预估；可 shrink-and-retry | 应加 400 分类与缩小重试 |
| 并行 | 类别间并发 + 段内串行（Pkg within_category=3） | LangExtract batch_length×max_workers 真并行 | 可提升段级并行 |

## 4. 推荐改进方案（按优先级）

### P0（直接消除超限/截断风险）

1. **窗口与字符比联动模型配置**：`llm_extractor.py` 的 `MODEL_CONTEXT_WINDOW_TOKENS` 改为从 KB「资源与配置」读取模型参数或启动时探测 `/v1/models`；`chars_per_token` 改用模型 tokenizer 精确计数（vLLM 本地模型可用 `transformers.AutoTokenizer`，tiktoken 兜底），无法精确时对中文取 1.5、英文取 4 的混合估算。
2. **清除 BaseExtract 截断**：`llm_extractor.py::extract_category` 去掉 `context_truncate`，与 LangExtractPkg 统一为「全量上下文 + 分段多次抽取」。
3. **输出预算动态化**：`max_tokens` 默认从 32768 下调（建议 8192），按类别字段数预估输出；输入预算随 max_tokens 自动放大，从根本上降低「输入太长 + 输出预算太大」导致的 400。

### P1（提升抽取质量与健壮性）

4. **语义边界切分**：`split_context` 从纯字符窗口改为优先按版面块/段落/句子边界切（复用 chunker 的 `_SENTENCE_END_RE` 与 layout 块边界），保证不拆断表格/条款；overlap 处加 `[--上下文接续--]` 标记（对齐入库块语义）。
5. **400 错误分类 + 缩小重试**：`llm_client.py` 对响应文本匹配 context-over-limit 特征（"maximum context length"等），命中后把该段按语义边界再二分重试，仍失败才整体失败。
6. **合并策略升级**：去重从 JSON 全等改为「按主键字段（如材料牌号）合并 + 置信度/命中分数择优」，跨段同一实体只保留信号最强记录。

### P2（可选增强）

7. **段级并行**：LangExtractPkg 段内并行（batch_length×max_workers），受 KB 并发限制约束。
8. **页边界分块选项**：入库分块器增加 by_page 策略（Unstructured 风格）。
9. **上下文压缩**：上下文超长时按相关性排序丢弃低分块并记录丢弃统计（而非静默截断）。

## 5. 结论

- 本系统**入库分块（2000 字符、句子边界、表格独立）与主流一致**，无需改动；
- 主要风险集中在**抽取上下文侧**：窗口硬编码、字符估算粗、BaseExtract 残留截断、纯字符窗口切分、400 无兜底、合并策略粗糙；
- 优先落地 P0 三项即可消除「截断/超限」类问题；P1 语义切分与 400 重试可显著降低 GB-T1220 这类长表文档的抽取失败率。
