# 向量化与入库链路对比方案（lightRAG vs 原项目，2026-08）

> 更新（2026-08-11）：D1-D8 决策已确认（D2=BGE-M3、D3=Title+Content 双向量、D6=dense+BM25+RRF、D4=jieba BM25），落地实施见 [INDEXING_IMPLEMENTATION_PLAN.md](INDEXING_IMPLEMENTATION_PLAN.md)。

> 背景：OCR 解析链路已定版（V3 + GLM-OCR）。本方案对比 lightRAG 与
> document-parser-rag-system 在"解析之后 → 分块 → 嵌入 → 入库 → 检索"的链路，
> 供决策取舍。约束：向量库/图库用 PostgreSQL、KB RLS 隔离、MinIO 存储。

## 1. lightRAG 链路（源码：lightrag/lightrag/）

```
解析（pdf/vlm/pipeline）→ full_docs（全文存储）
  → process_single_document：
      分块（默认 F=token窗口，可选 P=段落语义/R=递归字符/V=语义向量）
      → 嵌入（embedding_func 批量）
      → 并行写入：chunks_vdb（向量）+ text_chunks（KV 全文）
      → Stage2：LLM 抽取实体/关系 → 图存储（neo4j/networkx/pgtable）
查询：naive(纯向量) / local(图局部) / global(图全局) / hybrid(向量+图) / mix
  + 可选 rerank（rerank.py）
```

关键实现：
- 分块调度：`pipeline.py`（F/P/R/V 策略分发，`chunking_by_fixed_token` 等）
- 嵌入：存储层批量调用 `embedding_func`（`postgres_impl.py` `_flush_pending_vector_ops`）
- 向量表：`LIGHTRAG_VDB_CHUNKS`（pgvector，字段：id/workspace/full_doc_id/chunk_order_index/tokens/content/content_vector/file_path/heading/sidecar）
- 全文块：`text_chunks` KV（content + 元数据）
- 图：LLM 抽取实体/关系（`operate.py` merge_nodes_and_edges）
- chunk 元数据：heading（层级面包屑）、sidecar（block/drawing/table/equation）、tokens

## 2. 原项目链路（源码：document-parser-rag-system/）

```
OCR + Popo 重建 → DocumentElement（层级结构）
  → HierarchyChunker：按 hierarchy_path 分 ParentChunk → 句段切 ChildChunk
    （2000字符、200 overlap、层级继承、parent_text）
  → 五维向量嵌入（bge-m3）：Path/Title/Content/Type/Structural
  → Milvus doc_chunks_{kb}：dense + sparse 混合
查询：hybrid_search（dense + sparse + RRF 融合 + ef 参数）
辅助：table_enhancer（表格增强）、caption_linker、bm25_retriever
```

关键实现：
- 分块：`services/vector/chunker.py`（层级父子块，语义边界切分）
- 嵌入：`services/vector/five_dim_embedder.py`（5 维 × bge-m3）
- 存储：`services/vector/chunk_vector_store.py`（Milvus，按 kb 分 collection）
- 检索：`hybrid_search`（dense IP + sparse IP → RRF 融合）

## 3. 逐环节对比

| 环节 | lightRAG | 原项目 | 关键差异 |
|------|----------|--------|----------|
| 分块策略 | token 窗口（默认 1200/300）| 层级父子块（章节分组+句段切分）| 原项目保留文档层级，lightRAG 默认无层级（heading 元数据有） |
| 分块元数据 | heading/sidecar/tokens/order | hierarchy_path/parent_id/level/title/parent_text/semantic_label/source_pages | 原项目语义标签+来源页更细 |
| 嵌入 | 单向量（可配模型）| 五维向量（bge-m3）| 原项目结构感知更强 |
| 向量库 | 可插拔（pgvector 等）| Milvus | **pgvector 契合我们的 PostgreSQL 约束** |
| 全文存储 | text_chunks KV | 无独立全文 KV（Milvus 存 text）| lightRAG 有全文 KV，便于溯源 |
| 图 | LLM 实体/关系 → 图存储 | 无图 | lightRAG 有完整图链路 |
| 检索 | 向量+图 5 模式 + rerank | dense+sparse RRF | lightRAG 检索更丰富 |
| 表格处理 | sidecar table markup | table_enhancer | 原项目表格专项增强 |
| KB 隔离 | workspace | kb_id 分 collection | 均支持，需映射到 RLS |
| 重排 | rerank.py 可选 | 无 | lightRAG 可接重排模型 |

## 4. 推荐取舍（待用户决策）

### 方案 A：lightRAG 链路为主（契合"向量库/图库用 PostgreSQL"）
- 分块：F（token 窗口）为基础，P（段落语义）适配标准文档
- 嵌入：单向量（可选 bge-m3），接 pgvector
- 图：LLM 实体/关系抽取 → PG 图（pgtable）
- 检索：hybrid（向量+图）+ rerank
- 优点：工程完整、可插拔、图链路现成、pgvector 契合
- 代价：分块无层级结构（需改造接入我们 layout.json 的层级）、五维向量缺失（结构化检索弱）

### 方案 B：原项目链路为主（保留五维向量 + 层级分块）
- 分块：HierarchyChunker（消费我们 layout.json 的层级树）
- 嵌入：五维向量（bge-m3）
- 向量库：Milvus → 改 pgvector（迁移）
- 检索：dense+sparse RRF
- 优点：层级/语义标签/表格增强成熟，与标准文档场景匹配
- 代价：无图链路（需补）、Milvus 迁移 pgvector、检索模式单一

### 方案 C：融合（推荐）
- 分块：**原项目 HierarchyChunker**（消费 layout.json 层级，语义完整）
- 嵌入：**五维向量为主 + 可加轻量单向量**（保留结构感知）
- 向量库：**pgvector**（迁移原项目 Milvus 存储为 PG 表 + HNSW 索引）
- 全文：text_chunks 表（lightRAG 思路，溯源用）
- 图：**lightRAG 的 LLM 实体抽取 → PG 图**（pgtable 或自定义 RLS 表）
- 检索：hybrid（dense+sparse+RRF）+ 图检索（local/global）+ 可选 rerank
- KB 隔离：所有表按 kb_id + RLS
- 优点：层级分块 + 五维向量 + PG 向量/图 + 检索丰富，兼顾两者

## 5. 待用户决策点

1. 分块：token 窗口（lightRAG）还是层级父子块（原项目）？
2. 嵌入：单向量还是五维向量？（五维每子块 5 次嵌入，成本 5 倍）
3. 图：是否要 LLM 实体/关系抽取（成本高）？还是先向量 RAG 后补图？
4. 检索：naive 先行还是直接上 hybrid（向量+图+rerank）？
5. 表格：原项目 table_enhancer 是否保留？
6. 全文 KV：是否需要独立 text_chunks 表（溯源/引用）？

> 参考源码：lightrag/lightrag/{pipeline.py, operate.py, kg/postgres_impl.py, chunker/}；
> document-parser-rag-system/backend/app/services/vector/{chunker.py, five_dim_embedder.py, chunk_vector_store.py}
