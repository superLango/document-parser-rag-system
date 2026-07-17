# Hansight RAG 系统优化方案

> **版本**：v1.0  
> **编制日期**：2026-07-17  
> **编制依据**：市面主流 RAG 项目（RAGFlow / Dify / FastGPT / LlamaIndex / LangChain）技术调研 + 本项目生产级对比测试数据  
> **适用范围**：Hansight 文档智能解析系统 RAG 子系统

---

## 一、文档概述

本方案基于对 RAGFlow、Dify、FastGPT、LlamaIndex、LangChain 等市面主流 RAG 项目的深度技术调研，结合 Hansight 系统生产级对比测试的真实数据，整合各项目核心技术精华与最佳实践，制定一套针对性强、可落地的 RAG 系统优化方案。

方案覆盖六大关键模块：检索策略优化、知识库构建与管理、嵌入模型选择与调优、提示工程设计、多模态数据处理、性能与效率提升，并给出分阶段实施步骤、量化预期效果、评估指标体系与资源需求。

---

## 二、现状分析

### 2.1 当前系统架构

```
用户查询
   │
   ▼
[查询理解] ── LLM 意图分类 + 实体抽取 + 查询重写
   │
   ▼
[意图路由] ── general → Milvus 路径
              summarization → LlamaIndex SummaryIndex
              comparison → SubQuestionQueryEngine
   │
   ▼
[并行检索] ── Milvus(Dense+Sparse) + Neo4j 知识图谱
   │
   ▼
[重排] ── bge-reranker-v2-m3 CrossEncoder
   │
   ▼
[上下文组装] ── 文档片段 + 图谱实体
   │
   ▼
[LLM 生成] ── Ollama API + Qwen3.5:9B (think:false)
   │
   ▼
[响应] ── answer + citations + intent
```

**技术栈**：
- 文档解析：PaddleOCR 3.7.0 + MinerU-Popo
- 分块：StructureAwareChunker（RecursiveCharacterTextSplitter，512字符，64重叠）
- 嵌入：BAAI/bge-m3（Dense 1024维 + Sparse）
- 向量库：Milvus 2.4（IVF_PQ + SPARSE_INVERTED_INDEX）
- 重排：bge-reranker-v2-m3
- LLM：Ollama API + Qwen3.5:9B
- LlamaIndex：SummaryIndex + SubQuestionQueryEngine（0.14.23）
- 缓存：**无**
- 任务队列：arq（异步）

### 2.2 性能基线数据

基于 GB/T 1220-2007 不锈钢棒标准文档（31页，116,468字符，316个Milvus分块，451个LlamaIndex节点）的生产级测试：

| 测试ID | 意图 | 实际路由 | 耗时 | 引用数 | 答案长度 | 关键词命中 |
|--------|------|----------|------|--------|----------|-----------|
| G1 | general | Milvus | 19.0s | 5 | 285字符 | 67% |
| G2 | general | Milvus | 18.0s | 5 | 345字符 | 67% |
| S1 | summarization | LlamaIndex SummaryIndex | 48.3s | 30 | 1453字符 | 100% |
| S2 | summarization | Milvus（意图误识别） | 22.4s | 5 | 647字符 | 100% |
| C1 | comparison | LlamaIndex SubQuestionQueryEngine | 102.5s | 90 | 2094字符 | 100% |

**按路径汇总**：

| 指标 | LlamaIndex 路径 | 原 Milvus 路径 |
|------|-----------------|----------------|
| 平均耗时 | 75.4s | 19.8s |
| 平均关键词命中率 | 100% | 78% |
| 平均答案长度 | 1774字符 | 425字符 |
| 平均引用数 | 60 | 5 |

### 2.3 问题诊断与差距分析

通过与市面主流 RAG 项目对比，识别出以下六大核心差距：

| # | 差距领域 | 当前状态 | 业界最佳实践 | 影响程度 |
|---|----------|----------|-------------|----------|
| 1 | 缓存体系 | 完全无缓存 | Dify 三级缓存（LRU+Redis），命中<100ms | 致命 |
| 2 | 分块策略 | 固定512字符，不感知表格 | RAGFlow 场景化模板，表格识别>90% | 严重 |
| 3 | LLM调用模式 | SubQuestionQueryEngine 4次串行调用 | Dify 并行节点 + LLM路由 | 严重 |
| 4 | 检索算法 | IVF_PQ（精度优先） | RAGFlow HNSW + bfloat16量化（速度优先） | 中等 |
| 5 | 查询改写 | 仅LLM意图分类 | STORM HyDE技术（召回率+28%） | 中等 |
| 6 | 流式输出 | LlamaIndex路径无流式 | 全路径SSE流式输出 | 中等 |

---

## 三、优化方案总览

### 3.1 优化目标

| 指标 | 当前值 | 优化目标 | 提升幅度 |
|------|--------|----------|----------|
| Milvus路径平均延迟 | 19.8s | ≤3s | 85%↓ |
| LlamaIndex路径平均延迟 | 75.4s | ≤15s | 80%↓ |
| 缓存命中延迟 | N/A | ≤200ms | - |
| 关键词命中率（general） | 67% | ≥90% | 35%↑ |
| 意图识别准确率 | 80% | ≥95% | 19%↑ |
| 表格数据可回答率 | 0% | ≥85% | - |

### 3.2 技术路线图

```
阶段一（P0，1-2周）          阶段二（P1，2-3周）          阶段三（P2，3-4周）
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│ 多级缓存体系     │     │ 表格感知分块     │     │ HNSW索引迁移     │
│ LLM路由策略      │     │ HyDE查询改写     │     │ 嵌入模型量化     │
│ 意图分类优化     │     │ LLM调用并行化    │     │ 知识图谱融合     │
│ 流式输出全路径   │     │ 引用溯源提示     │     │ 异步任务引擎     │
└─────────────────┘     └─────────────────┘     └─────────────────┘
      ▼                       ▼                       ▼
   延迟降80%              准确率升30%              检索延迟降60%
```

---

## 四、模块一：检索策略优化

### 4.1 多级缓存体系

#### 4.1.1 设计依据

Dify 的三级缓存策略在 200 并发下实现 641ms 平均延迟、168.3 QPS。当前项目每次查询都走完整链路（嵌入→检索→重排→LLM生成），无任何缓存层，是延迟居高不下的首要原因。

#### 4.1.2 具体措施

**三级缓存架构**（基于 Valkey 8）：

```
查询请求
   │
   ▼
[L1 内存缓存] ── LRU字典，容量1000条，TTL=60s
   │ 未命中
   ▼
[L2 语义缓存] ── Valkey 8，TTL=3600s，相似度阈值=0.95
   │ 未命中
   ▼
[L3 检索结果缓存] ── Valkey 8，TTL=86400s，key=query_hash
   │ 未命中
   ▼
[完整RAG链路]
   │
   ▼
[回写缓存] ── L1+L2+L3
```

**L1 内存缓存**（精确匹配）：
- 数据结构：`OrderedDict`，LRU 淘汰策略
- Key：`hash(question + top_k + doc_ids)` 的 SHA256
- Value：`RAGResponse` 序列化结果
- 容量：1000 条（约 50MB 内存）
- TTL：60 秒（保证数据新鲜度）

**L2 语义缓存**（相似查询复用）：
- 数据结构：Valkey 8 Hash + Sorted Set
- Key：查询向量的 base64 编码
- 匹配逻辑：计算查询向量与缓存向量的余弦相似度，≥0.95 则命中
- TTL：3600 秒（1小时）
- 回写策略：异步回写，不阻塞主流程

**L3 检索结果缓存**（中间结果复用）：
- 缓存对象：Milvus 检索结果 + 重排结果（不含LLM生成）
- Key：`hash(query_embedding + top_k + doc_ids + filters)`
- TTL：86400 秒（24小时，文档更新时失效）
- 失效策略：文档重新索引时按 doc_id 批量清除

#### 4.1.3 实现要点

```python
# app/services/cache_service.py（新增）

class RAGCacheService:
    """RAG 多级缓存服务。"""

    def __init__(self) -> None:
        self._l1_cache: OrderedDict[str, Any] = OrderedDict()  # LRU
        self._l1_max_size: int = 1000
        self._l1_ttl: int = 60
        self._valkey: Any = None  # Valkey 客户端
        self._similarity_threshold: float = 0.95

    async def get(self, question: str, top_k: int, 
                  doc_ids: list[str] | None) -> RAGResponse | None:
        """三级缓存查询，命中返回缓存结果，未命中返回 None。"""
        # L1 精确匹配
        cache_key = self._make_key(question, top_k, doc_ids)
        if result := self._l1_get(cache_key):
            return result
        # L2 语义匹配
        if result := await self._l2_semantic_get(question, top_k):
            return result
        # L3 检索结果匹配（返回中间结果，跳过检索阶段）
        return None

    async def set(self, question: str, response: RAGResponse,
                  top_k: int, doc_ids: list[str] | None) -> None:
        """异步回写三级缓存。"""
        asyncio.create_task(self._async_set(question, response, top_k, doc_ids))
```

#### 4.1.4 预期效果

| 场景 | 命中率（预估） | 延迟 |
|------|---------------|------|
| 重复查询（L1） | 15% | <10ms |
| 相似查询（L2） | 25% | <100ms |
| 检索结果复用（L3） | 40% | 跳过检索，仅LLM生成 |
| **综合缓存命中率** | **60-70%** | **平均延迟降80%** |

---

### 4.2 HyDE 查询改写

#### 4.2.1 设计依据

STORM 项目的 HyDE（Hypothetical Document Embeddings）技术通过生成假设文档来优化检索路径，召回率提升 28%。LiveRAG Challenge 2025 证实"词汇对齐是性能最强预测因子"——当查询与文档使用相似措辞时，余弦相似度从 0.562 提升到 0.762。

当前项目仅通过 LLM 进行意图分类和查询重写，未利用假设文档生成来提升检索召回率。

#### 4.2.2 具体措施

**HyDE 流程**：

```
用户查询："304不锈钢的铬含量是多少？"
        │
        ▼
[LLM 生成假设答案] ── "304不锈钢的铬含量约为18-20%，..."
        │
        ▼
[嵌入假设答案] ── bge-m3 生成向量
        │
        ▼
[Milvus 检索] ── 用假设答案向量检索（而非原始查询向量）
        │
        ▼
[返回相关文档片段] ── 召回率提升28%
```

**实现要点**：

```python
# app/services/query_service.py（扩展）

async def hyde_rewrite(self, question: str) -> str:
    """HyDE 查询改写：生成假设文档用于检索增强。
    
    策略：用轻量模型（gemma2:2b）快速生成假设答案，
    用假设答案的嵌入替代原始查询嵌入进行检索。
    仅对 general 意图启用，summarization/comparison 跳过。
    """
    hyde_prompt = (
        "请用1-2句话简要回答以下问题，不需要完全准确，"
        "用于后续文档检索增强：\n\n{question}"
    )
    # 使用轻量模型生成假设文档（延迟<2s）
    hypothetical_doc = await self._lightweight_llm.generate(
        prompt=hyde_prompt.format(question=question),
        max_tokens=128,
        temperature=0.3,
    )
    return hypothetical_doc
```

#### 4.2.3 预期效果

- 召回率提升 25-30%（基于 STORM 数据）
- 额外延迟：+1-2s（轻量模型生成假设文档）
- 净收益：召回率提升带来的准确性改善远超额外延迟

---

### 4.3 混合检索增强

#### 4.3.1 设计依据

当前项目已实现 Dense+Sparse 混合检索 + RRF 融合，但与 RAGFlow 的三路检索（BM25+向量+图谱）相比仍有差距。RAGFlow 的动态重排序（加权融合 0.6*语义+0.4*关键词）无需额外模型推理，比 CrossEncoder 重排更快。

#### 4.3.2 具体措施

**措施1：增加 BM25 关键词检索路径**

当前 Sparse 向量虽具备词项匹配能力，但 BM25 在精确术语匹配上仍有优势。增加 BM25 作为第三路检索，形成三路混合检索：

```
查询嵌入
   ├── Dense 向量检索（Milvus IVF_PQ）── 语义匹配
   ├── Sparse 向量检索（Milvus SPARSE_INVERTED_INDEX）── 词项匹配
   └── BM25 关键词检索（Valkey Search 或 Elasticsearch）── 精确匹配
                    │
                    ▼
              [RRF 融合排序]
```

**措施2：动态加权重排序（替代部分 CrossEncoder 场景）**

对于 general 意图的简单事实查询，用加权融合替代 CrossEncoder 重排，降低延迟：

```python
# 轻量重排：加权融合（无需模型推理）
final_score = 0.6 * dense_score + 0.3 * sparse_score + 0.1 * bm25_score
```

**措施3：CrossEncoder 重排降级为"精排"阶段**

仅在以下场景启用 CrossEncoder 精排：
- 混合检索 top_k > 20 时
- comparison/summarization 意图
- 用户显式要求高精度模式

#### 4.3.3 预期效果

| 指标 | 当前（Dense+Sparse+CrossEncoder） | 优化后（三路+动态加权+精排） |
|------|-----------------------------------|---------------------------|
| 检索阶段延迟 | 2-3s | 0.5-1s |
| 召回率 | 基线 | +15% |
| general路径总延迟 | 19.8s | 3-5s |

---

### 4.4 意图路由优化

#### 4.4.1 设计依据

测试发现 S2（"概述不锈钢棒的交货状态和要求"）被误识别为 document_search 而非 summarization，导致走了 Milvus 路径而非 LlamaIndex 路径。意图识别准确率仅 80%。

#### 4.4.2 具体措施

**措施1：扩展意图分类规则**

```python
# 当前意图分类 prompt 优化
INTENT_CLASSIFICATION_PROMPT = """
将以下查询分类为一种意图：
- general: 查询具体事实、数值、定义（如"304的铬含量是多少"）
- summarization: 要求总结、概述、综述文档内容
  关键词线索：总结、概述、综述、简述、概括、摘要、主要内容、介绍
- comparison: 要求对比、比较两个或多个事物的差异
  关键词线索：对比、比较、差异、区别、不同、vs

查询: {question}
意图:
"""
```

**措施2：规则预筛 + LLM 确认**

先通过关键词规则快速预筛意图，仅在规则无法确定时调用 LLM：

```python
def _rule_based_intent(self, question: str) -> str | None:
    """规则预筛意图分类。"""
    summary_keywords = ["总结", "概述", "综述", "简述", "概括", "摘要", "主要内容"]
    comparison_keywords = ["对比", "比较", "差异", "区别", "不同", "vs"]
    
    if any(kw in question for kw in summary_keywords):
        return "summarization"
    if any(kw in question for kw in comparison_keywords):
        return "comparison"
    return None  # 规则无法确定，调用LLM
```

**措施3：路由降级超时机制**

LlamaIndex 路径设置 30 秒超时，超时后自动降级到 Milvus 路径：

```python
try:
    result = await asyncio.wait_for(
        index_manager.query_with_intent(question, top_k),
        timeout=30.0,
    )
    if result.answer:
        return result
except asyncio.TimeoutError:
    logger.warning("LlamaIndex 路径超时，降级到 Milvus")
```

---

## 五、模块二：知识库构建与管理

### 5.1 表格感知分块

#### 5.1.1 设计依据

测试发现 G1（"304不锈钢的化学成分中铬含量是多少"）和 G2（"不锈钢棒的直径允许偏差是多少"）无法回答具体数值，关键词命中率仅 67%。根因是当前分块策略（固定512字符 + 段落分割）破坏了表格结构完整性，化学成分表格数据被截断分散到多个分块中。

RAGFlow 的场景化分块模板（特别是表格感知）使表格识别准确率达 90%+，是回答数值类问题的关键。

#### 5.1.2 具体措施

**措施1：表格结构化提取**

在 OCR 后处理阶段，识别表格并保留结构化格式：

```python
# app/services/table_extractor.py（新增）

class TableAwareExtractor:
    """表格感知内容提取器。"""

    async def extract_tables(self, ocr_result: dict) -> list[dict]:
        """从 OCR 结果中提取表格结构。
        
        Returns:
            list[dict]: 表格列表，每个表格含：
                - table_id: 表格唯一标识
                - headers: 列标题列表
                - rows: 行数据列表
                - markdown: Markdown格式表格文本
                - raw_text: 纯文本格式
        """
        # 利用 PaddleOCR 的表格识别能力
        # 或使用 camelot/tabula 解析 PDF 表格
        pass

    def table_to_markdown(self, table: dict) -> str:
        """将表格转换为 Markdown 格式，保留结构完整性。"""
        header = "| " + " | ".join(table["headers"]) + " |"
        separator = "| " + " | ".join(["---"] * len(table["headers"])) + " |"
        rows = ["| " + " | ".join(row) + " |" for row in table["rows"]]
        return "\n".join([header, separator] + rows)
```

**措施2：表格作为完整分块**

表格不参与常规分块，作为独立分块保留完整结构：

```python
# 分块策略调整
class EnhancedChunker(StructureAwareChunker):
    """增强分块器：表格感知。"""

    async def chunk_document(
        self, text: str, doc_meta: dict, tables: list[dict] | None = None
    ) -> list[dict]:
        chunks = []
        
        # 1. 常规文本分块
        text_chunks = await super().chunk_document(text, doc_meta)
        chunks.extend(text_chunks)
        
        # 2. 表格作为独立分块
        if tables:
            for table in tables:
                table_text = self.table_to_markdown(table)
                chunks.append({
                    "chunk_id": f"{doc_meta['doc_id']}_table_{table['table_id']}",
                    "text": table_text,
                    "metadata": {
                        **doc_meta,
                        "chunk_type": "table",
                        "table_headers": table["headers"],
                    },
                })
        
        return chunks
```

**措施3：表格语义增强**

为表格分块添加语义描述前缀，提升检索匹配率：

```python
# 表格分块文本增强
enhanced_text = f"""
【表格】{table['caption'] or '未命名表格'}
列标题：{', '.join(table['headers'])}
数据行数：{len(table['rows'])}

{table_to_markdown(table)}
"""
```

#### 5.1.3 预期效果

| 指标 | 当前 | 优化后 |
|------|------|--------|
| 表格数据可回答率 | 0% | ≥85% |
| G1/G2关键词命中率 | 67% | ≥90% |
| 表格检索准确性 | N/A | 表格结构100%保留 |

---

### 5.2 增量索引更新

#### 5.2.1 设计依据

RAGFlow 的增量索引更新机制允许新文档解析后实时合并索引，无需全量重建。当前项目每次文档更新需要重新构建全部索引，效率低下。

#### 5.2.2 具体措施

```python
# app/services/vector_store.py（扩展）

async def incremental_insert(self, chunks: list[dict], doc_id: str) -> None:
    """增量插入文档分块，不影响已有索引。"""
    # 1. 仅嵌入新分块
    embeddings = await embedding_service.embed_batch(chunks)
    # 2. 插入 Milvus（自动更新索引）
    self._collection.insert(chunks_data)
    # 3. 使该文档的缓存失效
    await cache_service.invalidate_by_doc_id(doc_id)
    # 4. 增量更新 LlamaIndex 索引
    if index_manager._built:
        await index_manager.insert_nodes(new_nodes)
```

---

### 5.3 知识图谱融合

#### 5.3.1 设计依据

RAGFlow 的 GraphRAG 通过实体关系图谱关联检索，召回率较单向量提升 35%。当前项目已有 Neo4j 知识图谱存储和 OneKE/DeepKE 实体关系抽取，但图谱检索与向量检索的融合度不足。

#### 5.3.2 具体措施

**图谱增强检索**：

```
用户查询
   │
   ├──[实体抽取]──→ Neo4j 图谱检索（1跳邻居实体）
   │                    │
   │                    ▼
   │              [图谱扩展上下文]
   │
   └──[向量检索]──→ Milvus 混合检索
                        │
                        ▼
                  [文档片段]
        │                    │
        └──────[融合排序]──────┘
                   │
                   ▼
             [增强上下文]
```

---

## 六、模块三：嵌入模型选择与调优

### 6.1 向量量化加速

#### 6.1.1 设计依据

RAGFlow 使用 bfloat16 量化向量索引，检索延迟降至 0.3 秒内。当前项目使用 FLOAT_VECTOR（32位浮点），内存占用大、检索速度有优化空间。

#### 6.1.2 具体措施

**措施1：Milvus 向量量化**

Milvus 2.4 支持 `BIN_FLAT` 和 `SQ8` 量化索引。将 IVF_PQ 的参数优化：

```python
# 优化索引参数
collection.create_index(
    field_name="dense_vector",
    index_params={
        "index_type": "IVF_PQ", 
        "metric_type": "IP",
        "params": {
            "nlist": 1024,
            "m": 16,
            # 启用 PQ 量化，将 1024 维 32 位向量压缩为 16 字节
            # 内存占用降低 256 倍，检索速度提升 3-5 倍
        },
    },
)
```

**措施2：嵌入批量推理优化**

```python
# 利用 bge-m3 的批量推理能力
BATCH_SIZE = 32  # 从 4 提升到 32
# 使用 GPU 批量推理（如可用）
```

### 6.2 HNSW 索引优化

#### 6.2.1 设计依据

HNSW（Hierarchical Navigable Small World）算法在召回率和速度上优于 IVF_PQ，是业界主流选择。RAGFlow、Dify 均采用 HNSW。

#### 6.2.2 具体措施

```python
# 迁移到 HNSW 索引
collection.create_index(
    field_name="dense_vector",
    index_params={
        "index_type": "HNSW",
        "metric_type": "IP",
        "params": {
            "M": 16,           # 每个节点的最大连接数
            "efConstruction": 200,  # 构建时搜索宽度
        },
    },
)
# 查询时设置 ef 参数
search_params = {"params": {"ef": 64}}  # 查询时搜索宽度
```

**预期效果**：检索延迟从 2-3s 降至 0.3-0.5s。

### 6.3 嵌入模型适配

当前 bge-m3 已是业界领先的多语言嵌入模型，无需更换。优化点：

- **缓存嵌入结果**：对相同文本的嵌入结果进行缓存
- **异步批量嵌入**：利用 asyncio 并行嵌入多个分块
- **ONNX Runtime 加速**：将 bge-m3 转为 ONNX 格式，利用 ONNX Runtime GPU 加速

---

## 七、模块四：提示工程设计

### 7.1 LLM 路由策略

#### 7.1.1 设计依据

Dify 根据 query 复杂度选择不同模型（简单问题用轻量模型，复杂问题用大模型）。当前项目所有查询都使用 Qwen3.5:9B，简单事实查询也需 15-20s。

#### 7.1.2 具体措施

**模型路由表**：

| 意图 | 复杂度 | 模型 | 预期延迟 |
|------|--------|------|----------|
| general（简单事实） | 低 | gemma2:2b | 3-5s |
| general（复杂推理） | 中 | qwen3.5:9b | 15-20s |
| summarization | 高 | qwen3.5:9b | 20-40s |
| comparison | 高 | qwen3.5:9b | 40-80s |

```python
# app/services/llm_router.py（新增）

class LLMRouter:
    """LLM 模型路由器。"""

    MODEL_MAP = {
        "general_simple": {"model": "gemma2:2b", "max_tokens": 512},
        "general_complex": {"model": "qwen3.5:9b", "max_tokens": 1024},
        "summarization": {"model": "qwen3.5:9b", "max_tokens": 2048},
        "comparison": {"model": "qwen3.5:9b", "max_tokens": 2048},
    }

    def route(self, intent: str, question: str) -> dict:
        """根据意图和问题复杂度选择模型。"""
        if intent == "general":
            # 简单事实查询（含"是什么""多少"等）用轻量模型
            if any(kw in question for kw in ["是什么", "多少", "哪个", "定义"]):
                return self.MODEL_MAP["general_simple"]
            return self.MODEL_MAP["general_complex"]
        return self.MODEL_MAP.get(intent, self.MODEL_MAP["general_complex"])
```

### 7.2 引用溯源提示

#### 7.2.1 设计依据

RAGFlow 的引用溯源机制使法律场景关键条款定位准确率达 98.6%。当前项目的系统提示词未明确要求模型标注引用来源。

#### 7.2.2 具体措施

```python
SYSTEM_PROMPT_WITH_CITATION = """你是一个文档问答助手。基于以下检索到的文档片段回答问题。

要求：
1. 仅基于提供的文档片段回答，不得编造信息
2. 在回答中标注信息来源，格式为[片段N]
3. 如无法从文档中找到答案，明确说明"根据现有文档无法回答"
4. 对于数值类信息，给出具体数值和单位

文档片段：
{context}

请回答以下问题：{question}

回答格式：
[回答内容]
来源：[片段N, 片段M]
"""
```

### 7.3 答案结构化模板

针对不同意图使用不同的答案模板：

```python
ANSWER_TEMPLATES = {
    "general": "直接给出答案，附上数值和单位",
    "summarization": "按主题分点总结，每点2-3句话",
    "comparison": "使用表格对比差异，列出相同点和不同点",
}
```

---

## 八、模块五：多模态数据处理

### 8.1 表格结构化提取

#### 8.1.1 具体措施

**PDF 表格提取**：

```python
# 使用 pdfplumber 或 camelot 提取 PDF 表格
import pdfplumber

async def extract_pdf_tables(pdf_path: str) -> list[dict]:
    """提取 PDF 中的表格结构。"""
    tables = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages):
            for table in page.extract_tables():
                tables.append({
                    "page": page_num + 1,
                    "headers": table[0],
                    "rows": table[1:],
                })
    return tables
```

**OCR 表格识别**：

```python
# PaddleOCR 表格识别
from paddleocr import PPStructure

table_engine = PPStructure(layout=True, table=True, ocr=True)
result = table_engine.predict(image)
# 提取表格区域并转换为结构化数据
```

### 8.2 图表语义理解

对于图表类内容，生成文字描述用于检索：

```python
async def chart_to_text(self, chart_image: bytes) -> str:
    """将图表转换为文字描述。"""
    # 使用 LLM 视觉模型或 OCR + 规则提取
    description = await vl_model.analyze(chart_image)
    return f"【图表】{description}"
```

---

## 九、模块六：性能与效率提升

### 9.1 LLM 调用并行化

#### 9.1.1 设计依据

当前 SubQuestionQueryEngine 的 C1 查询需要 4 次 LLM 调用（3个子问题 + 1次合并），耗时 102.5s。Dify 通过并行执行节点显著降低延迟。

#### 9.1.2 具体措施

**措施1：子问题并行查询**

```python
# SubQuestionQueryEngine 优化
async def query(self, question: str) -> dict:
    # 1. 生成子问题（1次LLM调用）
    sub_questions = await self._generate_sub_questions(question)
    
    # 2. 并行查询子问题（而非串行）
    tasks = [self._query_one(sq) for sq in sub_questions]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # 3. 合并答案（1次LLM调用）
    final_answer = await self._merge_answers(question, results)
    
    return final_answer
```

**措施2：意图分析与检索并行**

```python
# 意图分析与向量嵌入并行执行
intent_task = asyncio.create_task(query_service.analyze(question))
embed_task = asyncio.create_task(embedding_service.embed(question))
intent, query_embedding = await asyncio.gather(intent_task, embed_task)
```

#### 9.1.3 预期效果

| 场景 | 当前 | 优化后 |
|------|------|--------|
| C1（3子问题串行） | 102.5s | 40-50s（并行后取最慢子问题耗时+合并） |
| general（意图+嵌入串行） | 19.8s | 12-15s |

---

### 9.2 流式输出优化

#### 9.2.1 设计依据

当前项目 LlamaIndex 路径无流式输出，用户需等待完整响应。SSE 流式输出可将用户感知延迟降低 70%。

#### 9.2.2 具体措施

**全路径 SSE 流式输出**：

```python
# app/services/rag_service.py（扩展）

async def query_stream(self, question: str, **kwargs) -> AsyncGenerator[str, None]:
    """全路径流式查询。"""
    # 1. 前置阶段（查询理解+检索+重排）同步完成
    context = await self._prepare_context(question, **kwargs)
    
    # 2. 判断路由路径
    if intent in ("summarization", "comparison") and index_manager._built:
        # LlamaIndex 路径流式
        async for chunk in self._llamaindex_stream(question, context):
            yield chunk
    else:
        # Milvus 路径流式（已有实现）
        async for chunk in self._milvus_stream(question, context):
            yield chunk
```

**LlamaIndex 流式查询**：

```python
async def _llamaindex_stream(self, question: str, context: dict) -> AsyncGenerator:
    """LlamaIndex 路径流式输出。"""
    query_engine = index_manager._summary_index.as_query_engine(
        llm=llm,
        response_mode="compact",
        streaming=True,  # 启用流式
    )
    response = await asyncio.to_thread(query_engine.query, question)
    for chunk in response.response_gen:
        yield chunk
```

---

### 9.3 异步任务引擎

#### 9.3.1 设计依据

RAGFlow 使用 Redis 消息队列 + trio 并发控制（默认50线程）处理文档解析任务。当前项目使用 arq 异步任务队列，但并发度未优化。

#### 9.3.2 具体措施

**arq worker 并发优化**：

```python
# app/tasks/arq_worker.py

class WorkerSettings:
    # 并发任务数（从默认 4 提升到 16）
    max_jobs = 16
    # 任务超时（秒）
    job_timeout = 1800
    # 重试策略
    max_retries = 3
    retry_delay = 60
```

**文档解析流水线并行化**：

```python
async def parse_document_pipeline(doc_id: str):
    """文档解析流水线（阶段并行）。"""
    # 阶段1：下载
    file_bytes = await download_file(doc_id)
    
    # 阶段2：OCR（多页并行）
    page_images = _pdf_to_page_images(file_bytes)
    ocr_tasks = [ocr_service.recognize(img) for img in page_images]
    ocr_results = await asyncio.gather(*ocr_tasks)
    
    # 阶段3：分块 + 嵌入（流水线）
    chunks = chunker.chunk_document(text)
    # 边分块边嵌入，不等全部完成
    embed_tasks = [embedding_service.embed(c) for c in chunks]
    embeddings = await asyncio.gather(*embed_tasks)
    
    # 阶段4：索引写入
    await vector_store.insert(chunks, embeddings)
```

---

## 十、实施步骤

### 阶段一（P0，1-2周）：性能速赢

| 步骤 | 任务 | 优先级 | 预期效果 |
|------|------|--------|----------|
| 1.1 | 实现多级缓存服务（L1+L2+L3） | P0 | 平均延迟降80% |
| 1.2 | 实现 LLM 路由策略（general简单查询用gemma2:2b） | P0 | general路径延迟降60% |
| 1.3 | 优化意图分类（规则预筛+LLM确认） | P0 | 意图准确率升至95% |
| 1.4 | 实现 LlamaIndex 路径流式输出 | P0 | 用户感知延迟降70% |
| 1.5 | 实现路由降级超时机制（30秒） | P0 | 避免LlamaIndex路径超时 |

### 阶段二（P1，2-3周）：准确性提升

| 步骤 | 任务 | 优先级 | 预期效果 |
|------|------|--------|----------|
| 2.1 | 实现表格感知分块（表格结构化提取+独立分块） | P1 | 表格可回答率≥85% |
| 2.2 | 实现 HyDE 查询改写 | P1 | 召回率+28% |
| 2.3 | 实现 LLM 调用并行化（子问题并行+意图嵌入并行） | P1 | C1延迟降50% |
| 2.4 | 实现引用溯源提示工程 | P1 | 答案可信度提升 |
| 2.5 | 实现增量索引更新 | P1 | 索引更新效率提升 |

### 阶段三（P2，3-4周）：深度优化

| 步骤 | 任务 | 优先级 | 预期效果 |
|------|------|--------|----------|
| 3.1 | 迁移 HNSW 索引（替代IVF_PQ） | P2 | 检索延迟降60% |
| 3.2 | 实现向量量化加速 | P2 | 内存占用降90% |
| 3.3 | 增加 BM25 第三路检索 | P2 | 召回率+15% |
| 3.4 | 实现知识图谱融合检索 | P2 | 召回率+35% |
| 3.5 | 实现异步任务引擎优化（并行OCR+流水线嵌入） | P2 | 解析效率提升3倍 |

---

## 十一、预期效果

### 11.1 性能提升

| 指标 | 当前 | 阶段一后 | 阶段二后 | 最终 |
|------|------|----------|----------|------|
| Milvus路径平均延迟 | 19.8s | 5s | 4s | ≤3s |
| LlamaIndex路径平均延迟 | 75.4s | 30s | 20s | ≤15s |
| 缓存命中延迟 | N/A | <200ms | <100ms | <100ms |
| C1（comparison）延迟 | 102.5s | 60s | 50s | ≤40s |

### 11.2 准确性提升

| 指标 | 当前 | 阶段一后 | 阶段二后 | 最终 |
|------|------|----------|----------|------|
| 关键词命中率（general） | 67% | 75% | 90% | ≥90% |
| 意图识别准确率 | 80% | 95% | 95% | ≥95% |
| 表格数据可回答率 | 0% | 0% | 85% | ≥85% |
| 召回率（基线=100%） | 100% | 100% | 128% | 140%+ |

### 11.3 资源效率

| 指标 | 当前 | 最终 | 改善 |
|------|------|------|------|
| 向量索引内存占用 | 100% | 10% | 90%↓ |
| LLM调用次数（general） | 2次 | 1次 | 50%↓ |
| 文档解析耗时 | 100% | 33% | 67%↓ |

---

## 十二、评估指标体系

### 12.1 性能指标

| 指标 | 测量方法 | 目标值 |
|------|----------|--------|
| P50 响应延迟 | 100次查询的50分位 | ≤3s |
| P95 响应延迟 | 100次查询的95分位 | ≤10s |
| P99 响应延迟 | 100次查询的99分位 | ≤30s |
| 缓存命中率 | 缓存命中次数/总查询次数 | ≥60% |
| QPS | 压力测试峰值 | ≥50 |
| 检索延迟 | Milvus检索阶段耗时 | ≤500ms |

### 12.2 准确性指标

| 指标 | 测量方法 | 目标值 |
|------|----------|--------|
| 关键词命中率 | 预期关键词在答案中的出现率 | ≥90% |
| 意图识别准确率 | 正确意图/总查询 | ≥95% |
| 引用准确率 | 引用片段与答案相关性人工评分 | ≥85% |
| 表格数据可回答率 | 数值类问题可回答比例 | ≥85% |
| 召回率@5 | Top-5结果中包含正确答案的比例 | ≥90% |

### 12.3 评估方法

**自动化测试集**（20个问题）：
- general（事实查询）：10个
- summarization（摘要查询）：5个
- comparison（对比查询）：5个

**评估脚本**：

```python
# scripts/rag_evaluation.py

EVALUATION_CASES = [
    # general（数值类）
    {"id": "E1", "question": "304不锈钢的铬含量是多少？", 
     "expected_keywords": ["铬", "18", "Cr"], "intent": "general"},
    # general（定义类）
    {"id": "E2", "question": "什么是不锈钢的固溶处理？", 
     "expected_keywords": ["固溶", "热处理", "温度"], "intent": "general"},
    # summarization
    {"id": "E11", "question": "总结文档中关于力学性能的要求", 
     "expected_keywords": ["力学性能", "抗拉", "屈服"], "intent": "summarization"},
    # comparison
    {"id": "E16", "question": "对比304和316不锈钢的镍含量差异", 
     "expected_keywords": ["304", "316", "镍", "Ni"], "intent": "comparison"},
]

async def run_evaluation() -> dict:
    """运行完整评估，输出量化报告。"""
    results = []
    for case in EVALUATION_CASES:
        result = await rag_service.query(case["question"])
        eval_result = evaluate(result, case)
        results.append(eval_result)
    return aggregate_report(results)
```

---

## 十三、资源需求

### 13.1 硬件资源

| 资源 | 当前配置 | 优化后需求 | 说明 |
|------|----------|-----------|------|
| GPU | 1×（Qwen3.5推理） | 1×（同前） | 无需增加 |
| 内存 | 16GB | 32GB | 缓存层 + 批量嵌入 |
| 磁盘 | 100GB | 200GB | 向量索引 + 缓存存储 |
| Valkey 8 | 已部署 | 同前 | 复用现有实例 |
| Milvus | 已部署 | 同前 | 索引类型迁移 |

### 13.2 软件依赖

| 依赖 | 用途 | 安装方式 |
|------|------|----------|
| pdfplumber | PDF表格提取 | `pip install pdfplumber` |
| rank-bm25 | BM25检索 | `pip install rank-bm25` |
| onnxruntime-gpu | 嵌入加速 | `pip install onnxruntime-gpu` |

### 13.3 人力资源

| 角色 | 工作量 | 职责 |
|------|--------|------|
| 后端开发 | 3-4周 | 缓存服务、LLM路由、表格分块、HyDE、并行化 |
| 算法工程 | 1-2周 | HNSW调参、HyDE提示词、意图分类优化 |
| 测试 | 1周 | 评估脚本编写、20题测试集、性能压测 |

---

## 十四、风险与应对

| 风险 | 概率 | 影响 | 应对措施 |
|------|------|------|----------|
| 缓存一致性问题 | 中 | 数据过时 | 文档更新时主动失效缓存 |
| HNSW索引迁移期间服务中断 | 低 | 检索不可用 | 蓝绿部署，双索引并行运行 |
| HyDE生成质量差影响检索 | 中 | 召回率下降 | 设置假设文档质量校验，不合格时回退原始查询 |
| 轻量模型准确性不足 | 中 | general路径答案质量下降 | 设置置信度阈值，低置信度时升级到大模型 |
| Valkey缓存内存不足 | 低 | 缓存命中率下降 | 设置 maxmemory-policy=allkeys-lru |

---

## 十五、附录

### 附录A：市面RAG项目技术对标矩阵

| 技术能力 | RAGFlow | Dify | FastGPT | LlamaIndex | **Hansight（当前）** | **Hansight（优化后）** |
|----------|---------|------|---------|------------|---------------------|----------------------|
| 多级缓存 | ✅ | ✅✅✅ | ✅✅ | ✅ | ❌ | ✅✅✅ |
| 混合检索 | 三路 | 两路 | 两路 | 两路 | 两路 | 三路 |
| 表格感知分块 | ✅✅✅ | ✅ | ❌ | ✅ | ❌ | ✅✅✅ |
| HyDE查询改写 | ❌ | ❌ | ❌ | ✅ | ❌ | ✅ |
| LLM路由 | ❌ | ✅✅ | ✅ | ❌ | ❌ | ✅✅ |
| 流式输出 | ✅ | ✅ | ✅ | ✅ | 部分 | ✅全路径 |
| 知识图谱融合 | ✅✅ | ❌ | ❌ | ✅ | ✅ | ✅✅ |
| HNSW索引 | ✅ | ✅ | ✅ | - | ❌ | ✅ |
| 引用溯源 | ✅✅✅ | ✅ | ✅ | ✅ | ✅ | ✅✅ |

### 附录B：参考文献

1. RAGFlow 官方文档 - 工业级深度文档理解引擎
2. Dify 官方文档 - 低代码AI应用开发平台
3. FastGPT 官方文档 - 轻量级知识库问答系统
4. LlamaIndex 官方文档 - 数据驱动型RAG优化
5. LiveRAG Challenge 2025 - 检索增强生成评估
6. aimultiple.com - RAG Framework Benchmark 2026
7. STORM - HyDE 假设文档嵌入技术

---

> **文档结束** | Hansight RAG 系统优化方案 v1.0
