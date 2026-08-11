# 向量索引实施方案 V1.0（2026-08-11）

> 状态：D2/D3/D6 已确认；本文档为落地实施计划，按阶段执行，
> 每阶段完成后按 `qa/TESTING_PROCESS.md` 铁律执行五层测试。
>
> 关联文档：
> - [EMBEDDING_RESEARCH.md](EMBEDDING_RESEARCH.md)：D2 市面调研（模型/维度/检索）
> - [VECTOR_INDEX_PLAN.md](VECTOR_INDEX_PLAN.md)：lightRAG vs 原项目链路对比（方案 A/B/C）
> - [MAINFLOW_PLAN.md](MAINFLOW_PLAN.md)：主流程总案（D1-D10 架构基线）
> - [TESTING_PROCESS.md](../qa/TESTING_PROCESS.md)：测试铁律（M1-M32）

## 1. 决策基线（已确认）

| 编号 | 决策 | 结论 |
|------|------|------|
| D1 | 分块 | 消费 `layout.json` 层级树 + `result.md`，层级父子块，按业务优化 |
| D2 | 嵌入模型 | **BGE-M3（1024 维）**，本地权重 `models/bge-m3`，接口可插拔 |
| D3 | 向量维度 | **Title + Content 双向量**；Path/Type/Structural 转为结构化字段，不入向量 |
| D4 | 稀疏检索 | **jieba BM25**（KB 级增量统计，零 LLM，构建快） |
| D5 | 全文溯源 | 独立 `text_chunks` 表（lightRAG 思路），与向量块分离 |
| D6 | 检索 | dense（title+content 双路融合）+ jieba BM25 + RRF；**rerank 仅预留接口**；图检索不做 |
| D7 | 表格增强 | 保留 table_enhancer + table_cleaner，按当前业务裁剪 |
| D8 | 独立索引阶段 | indexing 为独立任务：解析失败不影响落库，可单独重试 |
| 基础 | 存储/隔离 | PostgreSQL + pgvector + MinIO + Redis/arq；**KB RLS 为第一边界** |

## 2. 目标数据流

```
解析完成（result.md + layout.json v1.2 已落 MinIO，document.status=completed）
    │  同一事务内写 outbox(type=document_index) → 自动触发（D8）
    ▼
index_document_task（arq / sync_executor）
    │ run_index_task(db, document_id, kb_id)
    ├─ 1. 读 MinIO：layout.json（pages.blocks + rebuild.document_tree）+ result.md
    ├─ 2. 分块（S2）：document_tree 层级 → ParentChunk/ChildChunk
    │     表格块：table_cleaner 清洗 + table_enhancer 自然语言增强前置（D7）
    ├─ 3. 嵌入（S3）：title_vector + content_vector（BGE-M3，批量、锁保护）
    ├─ 4. 幂等入库（S4/S5）：document_chunks + text_chunks + BM25 增量统计
    │     先清旧块（同一 doc），再批量 upsert；失败可重试不污染解析状态
    └─ checkpoint：stages=[chunking, enhancing, embedding, storing] + 进度
          → completed / failed（document.index_status 同步更新）

检索（S6）：
query ─► title 向量路（0.2）┐
        ► content 向量路（0.8）┴─ dense 融合 ─┐
        ► jieba BM25 词法路 ──────────────────┴─ RRF(k=60) ─► rerank 接口（预留）─► 结果
```

## 3. 原项目参考与移植原则（硬性约束）

> **禁止照搬**：所有参考 `document-parser-rag-system/` 的内容，只允许借鉴
> 已验证的设计思想与参数结论，代码必须按当前项目结构、数据契约、依赖与
> 工程规范重写；不得整文件复制、不得保留 Milvus/Popo 等已废弃组件接口。
> 每个移植点在交付时必须附"原实现 vs 新实现"差异说明。

### 3.1 逐模块移植对照

| 原项目文件 | 借鉴点 | 必须优化的差异（禁止照搬） |
|------------|--------|------------------------------|
| `services/vector/chunker.py` | 父子块层级继承、表格不切分、overlap（200 字符/2 句）、parent_text 上下文 | 输入从 Popo `merged.json` 改为 **layout.json v1.2 的 document_tree + pages.blocks**；层级面包屑由树深度遍历生成，不再依赖 Popo 栈式重建；块类型集合扩展（formula/image/image_caption/list_item/footnote 等），需定义各类型分块规则（formula 并入段落、image 不单独成文本块）；`source_pages` 对齐当前页面 0-based 约定；无 tree 时走降级路径 |
| `services/embedding/embedding_service.py` | BGE-M3 单例懒加载、`asyncio.Lock` 串行化防 torch fork、fp16、batch_size=16/max_length=8192 实测参数 | 默认用当前项目已有的 transformers 直接加载（不新增 FlagEmbedding，X3）；仅产出 dense；返回结构按新项目 schema 定义；配置项全部迁移到 `app/core/config.py`；日志/异常按当前规范 |
| `services/vector/five_dim_embedder.py` | 多文本一次批量 embed、不分组、return_sparse=False 的耗时结论 | **五维砍为双维**（title/content）；不再有 path/type/structural 向量字段与 DIMENSIONS 常量；增强文本只进 `content_for_embedding` |
| `services/vector/five_dim_vector_store.py` / `chunk_vector_store.py` | RRF 融合思想、per_dim top_k、候选放大 | **存储从 Milvus 改为 pgvector SQLAlchemy 模型**；五路 WeightedRanker 改为两次 ANN + 加权/RRF；无 SPARSE_FLOAT_VECTOR 字段；写入/删除改事务幂等；RLS 策略替代按 KB 分 collection |
| `services/extraction/retrieval/query_embedder.py` | 查询文本精简规则（去括号/去方法后缀） | 五维查询构造删除，改为 **title 文本 + content 文本双路**；不再为 path/type/structural 复制查询文本 |
| `services/extraction/retrieval/hybrid_searcher.py` | dense+keyword RRF、权重配置化 | 删除"词法命中=0 剔除类别"的抽取专用逻辑（通用检索不适用）；返回值走新 schema（不含 Milvus entity） |
| `services/vector/bm25_sparse.py` | jieba + ASCII 词元分词（元素符号/标准号/数值）、k1=1.5/b=0.75 | 存储从本地 JSON 文件 + Milvus sparse 改为 **PG `kb_bm25_stats` 增量统计 + `document_chunks.bm25_tokens`（GIN）**；不做稀疏向量格式转换；支持并发一致性（乐观锁/行锁） |
| `services/vector/table_enhancer.py` / `table_cleaner.py` | 表格概述/逐行描述/列统计、符号规范化、rowspan/colspan 展开 | 表格来源是 **GLM-OCR 输出 + 版面注行合并后的 HTML**（原版为 PaddleOCR/StructEqTable 输出），需先适配解析；增强文本只进 `content_for_embedding`，原始 HTML 保留在 content；规则按 GB/T 实测样本调优，不做原样搬运 |
| `reconstruction_service.py`（Popo 链路） | 层级重建/图文关联思想 | 当前项目已用 parsekit `rebuild.py`（build_tree）实现，**不迁移旧服务**；分块器直接消费新 document_tree |

### 3.2 交付检查项（每个阶段强制）

1. 新代码不得 import `document-parser-rag-system` 任何模块；
2. 不得出现 Milvus、Popo、merged.json、SPARSE_FLOAT_VECTOR 等旧概念；
3. 每个移植模块的交付说明包含"原实现 vs 新实现"差异表；
4. 复用原版参数结论（batch、overlap、RRF k）时必须在代码注释注明"结论来源与原版实测值"，但实现路径独立。

## 4. 新增/修改文件总览

### 后端（backend/）

| 文件 | 动作 | 内容 |
|------|------|------|
| `app/models/indexing.py` | 新增 | DocumentChunk / TextChunk / KbBm25Stats 模型 |
| `app/models/document.py` | 修改 | Document 增加 index_status/index_progress/index_total/index_error |
| `app/services/indexing/__init__.py` | 新增 | 包入口 |
| `app/services/indexing/models.py` | 新增 | DocumentElement / ParentChunk / ChildChunk 数据类 |
| `app/services/indexing/chunker.py` | 新增 | 层级父子分块器（消费 layout.json） |
| `app/services/indexing/table_cleaner.py` | 新增 | 迁移原版表格清洗器 |
| `app/services/indexing/table_enhancer.py` | 新增 | 迁移原版表格增强器（D7） |
| `app/services/indexing/bm25.py` | 新增 | jieba 分词 + KB 级 BM25 增量统计/打分（D4） |
| `app/services/indexing/retrieval.py` | 新增 | 检索服务：双向量 + BM25 + RRF（D6） |
| `app/services/indexing/reranker.py` | 新增 | 仅接口占位（本期不实现） |
| `app/services/embedding/__init__.py` | 新增 | 包入口 |
| `app/services/embedding/embedding_service.py` | 新增 | BGE-M3 嵌入服务（单例/懒加载/锁/批量） |
| `app/services/document_service.py` | 修改 | 增加 run_index_task / enqueue_index / 索引状态更新 |
| `app/tasks/sync_executor.py` | 修改 | outbox 按 type 路由（parse / index） |
| `app/tasks/arq_worker.py` | 修改 | 增加 index_document_task 与 type 路由 |
| `app/api/v1/endpoints/kb_indexing.py` | 新增 | 索引任务 + 检索 API |
| `app/api/v1/router.py` | 修改 | 注册 kb_indexing |
| `app/schemas/indexing.py` | 新增 | 检索请求/响应、索引任务 schema |
| `app/core/config.py` | 修改 | 嵌入/检索/BM25 配置项 |
| `alembic/versions/009_vector_indexing.py` | 新增 | pgvector 扩展 + 三张新表 + documents 索引状态列 + RLS |
| `requirements.txt` | 修改 | + `pgvector`、`jieba` |
| `scripts/download_embedding_model.py` | 新增 | 下载 BGE-M3 权重到 models/bge-m3 |

### 前端（frontend/）

| 文件 | 动作 | 内容 |
|------|------|------|
| `src/api/modules/indexing.ts` | 新增 | 检索/索引任务 API 封装 |
| `src/views/kb/KbVectorSearchPage.tsx` | 新增 | 向量搜索页（KB 内部菜单，替换占位） |
| `src/views/kb/KbDetailLayout.tsx` | 修改 | 向量搜索菜单接入真实页面 |
| `src/content/help.ts`、`docs/HELP_DOCS.md` | 修改 | 帮助文档补充向量搜索操作与截图 |

### 测试（qa/）

| 位置 | 内容 |
|------|------|
| `qa/unit/test_indexing_*.py` | L1：分块/BM25/融合/嵌入服务 |
| `qa/integration/test_indexing_*.py` | L2：解析→索引→检索全链路 |
| `qa/functional/test_vector_search_*.py` | L3：前端 E2E |
| `qa/boundary/test_indexing_boundary_*.py` | L4：边界/并发 |
| `qa/security/test_indexing_rls_*.py` | L5：越权/RLS/API Key |
| `qa/evaluation/retrieval_eval.py` | 检索召回评测（命中率/MRR） |
| `qa/results/INDEX_*.md` | 各阶段覆盖率统计与报告归档 |

## 5. 表结构设计（迁移 009）

### 4.1 document_chunks（向量块，检索主表）

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE document_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    kb_id UUID NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_id TEXT NOT NULL,                  -- '{document_id}_p{p_idx}_{c_idx}'
    parent_chunk_id TEXT,
    chunk_index INT NOT NULL,
    hierarchy_path TEXT NOT NULL DEFAULT '', -- 层级面包屑，如 "7 力学性能 > 7.4 拉伸试验"
    title TEXT NOT NULL DEFAULT '',          -- 章节标题（Title 向量来源）
    level INT NOT NULL DEFAULT 0,
    has_table BOOLEAN NOT NULL DEFAULT FALSE,
    semantic_label TEXT NOT NULL DEFAULT '', -- text/table/title/formula...
    source_pages JSONB NOT NULL DEFAULT '[]',
    content TEXT NOT NULL,                   -- 原始块正文（表格含 HTML）
    content_for_embedding TEXT,              -- 表格增强/题注前置后的嵌入文本
    parent_text TEXT,                        -- 父块完整原文（召回后替换上下文）
    tokens INT NOT NULL DEFAULT 0,
    title_vector VECTOR(1024),
    content_vector VECTOR(1024),
    bm25_tokens JSONB NOT NULL DEFAULT '{}', -- {token: count}，BM25 检索用
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ,
    deleted_at TIMESTAMPTZ,
    UNIQUE (document_id, chunk_id)
);

CREATE INDEX idx_chunks_kb_doc ON document_chunks (kb_id, document_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_chunks_title_vec ON document_chunks USING hnsw (title_vector vector_cosine_ops);
CREATE INDEX idx_chunks_content_vec ON document_chunks USING hnsw (content_vector vector_cosine_ops);
CREATE INDEX idx_chunks_bm25_tokens ON document_chunks USING gin (bm25_tokens);
```

说明：
- `title_vector` 编码 `hierarchy_path + title`（面包屑），负责章节定位；
- `content_vector` 编码 `content_for_embedding`（表格增强文本前置），负责语义召回；
- `bm25_tokens` 为 jieba 词元计数 JSONB（GIN 索引加速候选过滤）；
- 双向量 HNSW 使用 `vector_cosine_ops`（BGE-M3 已 L2 归一化，等价内积）。

### 4.2 text_chunks（全文溯源表，D5）

```sql
CREATE TABLE text_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    kb_id UUID NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_id UUID NOT NULL REFERENCES document_chunks(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    heading TEXT NOT NULL DEFAULT '',
    tokens INT NOT NULL DEFAULT 0,
    metadata JSONB NOT NULL DEFAULT '{}',   -- page/order/has_table/semantic_label/source_pages
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ,
    UNIQUE (document_id, chunk_id)
);
```

### 4.3 kb_bm25_stats（KB 级 BM25 统计，D4）

```sql
CREATE TABLE kb_bm25_stats (
    kb_id UUID PRIMARY KEY REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    payload JSONB NOT NULL DEFAULT '{}',   -- {n_docs, total_len, doc_freq}
    version INT NOT NULL DEFAULT 1,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

统计随文档索引**增量更新**（插入时 +n_docs/+total_len/+doc_freq，删除时回退），
避免整库重建；提供 `rebuild_bm25(kb_id)` 全量重建兜底（编辑器以上角色触发）。

### 4.4 documents 新增索引状态列

```sql
ALTER TABLE documents ADD COLUMN IF NOT EXISTS index_status VARCHAR(32) NOT NULL DEFAULT 'not_indexed';
ALTER TABLE documents ADD COLUMN IF NOT EXISTS index_progress INT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS index_total INT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS index_error JSONB;
```

状态机：`not_indexed → indexing → indexed / index_failed`；解析状态与索引状态互不覆盖。

### 4.5 RLS 策略（复用现有函数）

复用 `hansondoc_is_superuser()` / `hansondoc_current_kb()` /
`hansondoc_current_user()` / `hansondoc_kb_effective_role()`（005/006 迁移已建）：

| 表 | SELECT | INSERT/UPDATE/DELETE |
|----|--------|----------------------|
| document_chunks / text_chunks | 超管 或 当前 KB 有效成员 | 超管 或 当前 KB owner/admin/editor |
| kb_bm25_stats | 超管 或 当前 KB 有效成员 | 超管 或 当前 KB owner/admin/editor |

迁移同时 `ENABLE ROW LEVEL SECURITY` + `FORCE ROW LEVEL SECURITY`，
策略写法与 006 完全一致（当前用户空值经 `hansondoc_current_user()` 兜底，REG-15 不回归）。

## 6. 分块器设计（D1，S2）

输入：`layout.json`（schema 1.2）——优先消费 `rebuild.document_tree`（标题层级），
块内容回填自 `pages[].blocks[].content`（已含 GLM-OCR 结果与公式归并）。

```
document_tree 深度遍历 → 计算层级面包屑（"1 范围 > 1.1 术语"）
  → 叶子节点挂载 blocks（page/order/content）
  → 按 hierarchy_path 分组 → ParentChunk（完整章节）
  → 子块切分（继承 title/hierarchy_path/level/source_pages）
      ├─ 表格块：不切分，独立成块（复用 table_cleaner.is_table）
      ├─ 文本块：段落/句子边界切分，MAX_CHILD_CHARS=2000，overlap=200字符/2句
      └─ parent_text=父块完整原文（召回后替换上下文）
```

业务优化（相对原版 chunker.py）：
1. `semantic_label` 从块类型填充（text/table/title/formula），不再为空；
2. `source_pages` 精确到子块实际页，而非仅父块页；
3. 标题 fallback：优先树节点文本 → 其次路径末段 → 兜底"文档根节点"；
4. 无 document_tree 时降级：按块顺序走"文档根节点"单父块（不崩溃，记日志）；
5. 表格增强文本只进 `content_for_embedding`，`content` 保留原始 HTML（供抽取/溯源）。

## 7. 嵌入服务设计（D2，S3）

- 模型：BGE-M3（1024 维，dense only），权重放 `models/bge-m3`；
- 加载：单例 + 懒加载 + fp16 + GPU（`EMBEDDING_DEVICE` 可切 cpu）；
- 并发：`asyncio.Lock` 串行化（沿用原版防 torch fork 崩溃的成熟方案）；
- 批量：`batch_size=16`、`max_length=8192`（大表格块友好）；
- 实现：优先用已有 `transformers` 直接加载 + 均值池化（不新增 FlagEmbedding 依赖），
  若实测池化方式与 FlagEmbedding 有差异再回退 FlagEmbedding（留接口）;
- 可插拔：`EmbeddingProvider` 抽象，模型名/维度/路径全部配置化；
- 下载脚本：`scripts/download_embedding_model.py`（HF 或镜像），权重缺失时给出明确报错。

## 8. 索引任务状态机设计（D8，S4）

### 7.1 任务模型

- 复用 `DocumentTask` + `TaskOutbox`：`type="document_index"`；
- `task_id` 前缀 `idx-`（与解析 `ocr-` 区分）；
- checkpoint：`{"stages": ["chunking","enhancing","embedding","storing"], "chunks": n}`；
- 进度：`document.index_progress/index_total`（按块数反馈）。

### 7.2 触发

1. **自动**：解析任务 completed 的事务内，同事务写 DocumentTask + TaskOutbox
   （保证不丢单；若该文档已有 pending/running 索引任务则跳过）；
2. **手动**：`POST /api/v1/kbs/{kb_id}/documents/{document_id}/index`（editor+），
   若已有 running 任务返回 409，其余创建新任务。

### 7.3 幂等与失败隔离

- 执行前删除该文档旧块（`document_chunks` / `text_chunks` 同事务硬删）；
- 失败仅置 `document.index_status=index_failed` + `index_error`，
  `document.status` 保持 `completed`（解析产物不受影响）；
- 重试沿用 arq `max_tries` / 指数退避，超限进 `task_dead_letter`；
- sync 与 arq 共用同一 `run_index_task` 状态机（与解析任务同模式）。

## 9. BM25 设计（D4，S5）

- 分词（迁移原版 `bm25_sparse.py`）：正则提取 ASCII 词元
  （元素符号 C/Cr/Mo、标准号 GB/T 223、数值范围 0.015~0.060），
  剩余中文用 jieba；
- 统计粒度：**按块计 df**（与原版一致，召回粒度=检索粒度）；
- 增量维护：文档入库时更新 `kb_bm25_stats.payload`；
  - n_docs += 块数；total_len += 每块词元数；doc_freq 按 token 合并；
  - 删除/重索引时回退（删除块统计再插入新块统计）；
- 打分：查询 tokenize → SQL 用 `bm25_tokens ?| :tokens` 取候选 → Python 计算
  BM25（k1=1.5, b=0.75，参数配置化）；
- 全量重建：`POST /api/v1/kbs/{kb_id}/index/bm25/rebuild`（editor+）。

## 10. 检索服务与 API 设计（D6，S6）

### 9.1 检索流程

```
query ──► title 路：title_vector 余弦近邻（top_k*2）
        ► content 路：content_vector 余弦近邻（top_k*2）
        ► BM25 路：jieba 词法打分（top_k*2）
        ► 融合：
           dense_score = w_t*title + w_c*content（默认 0.2/0.8，配置化）
           final = RRF(dense_rank, bm25_rank, k=60, dense_w=1.0, keyword_w=1.2)
        ► rerank 接口占位（本期直通）
        ► 返回：chunk_id/content/parent_text/hierarchy_path/title/source_pages/doc_id
```

### 9.2 检索参数（默认值，配置化）

| 配置 | 默认 | 说明 |
|------|------|------|
| `RETRIEVAL_TITLE_WEIGHT` | 0.2 | title 路权重 |
| `RETRIEVAL_CONTENT_WEIGHT` | 0.8 | content 路权重 |
| `RETRIEVAL_RRF_K` | 60 | RRF 平滑常数 |
| `RETRIEVAL_KEYWORD_WEIGHT` | 1.2 | BM25 路权重（沿用原版） |
| `RETRIEVAL_TOP_K` | 10 | 默认返回数 |
| `RETRIEVAL_CANDIDATE_MULT` | 2 | 每路候选 top_k*2 |

### 9.3 API

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| POST | `/api/v1/kbs/{kb_id}/search` | 有效成员 | 检索（可带 document_id/has_table/level 过滤） |
| POST | `/api/v1/kbs/{kb_id}/documents/{document_id}/index` | editor+ | 手动触发/重索引 |
| GET | `/api/v1/kbs/{kb_id}/index/tasks` | 有效成员 | 索引任务列表 |
| POST | `/api/v1/kbs/{kb_id}/index/bm25/rebuild` | editor+ | BM25 全量重建 |

所有端点经 `get_kb_context` 激活 RLS；service 层 `require_role` 作为第一道闸。

## 11. 分阶段实施计划（每阶段铁律验收）

### S1 存储底座（pgvector + 表 + RLS）

范围：迁移 009、indexing 模型、requirements 依赖。
产出：`009_vector_indexing.py`、`app/models/indexing.py`、`app/models/document.py` 修改。
验收：`alembic upgrade/downgrade` 幂等；RLS 策略存在且生效；表约束/索引创建成功。
测试：M24（L1 模型/迁移逻辑，L2 迁移+RLS 集成，L4 重复迁移/空 user 上下文，
L5 非成员读写越权）。

### S2 层级父子分块器 + 表格增强（D1/D7）

范围：chunker + table_cleaner + table_enhancer + 数据类。
产出：`app/services/indexing/{models,chunker,table_cleaner,table_enhancer}.py`。
验收：用真实解析产物 `qa/fixtures/layout_sample.json` 跑通；
表格不切分、层级继承、overlap、parent_text、source_pages 均正确。
测试：M25 + M27（L1 分块规则/增强规则，L2 真实产物集成，
L4 空树/根节点/超长章节/无标题/畸形表格，L5 无）。

### S3 嵌入服务（D2）

范围：BGE-M3 加载与批量编码 + 下载脚本 + 配置。
产出：`app/services/embedding/embedding_service.py`、`scripts/download_embedding_model.py`。
验收：权重下载至 `models/bge-m3`；首次调用输出 1024 维归一化向量；
空输入不触发模型；长文本按 8192 截断；并发调用不崩溃。
测试：M26（L1 编码/截断/归一化，L2 与分块器集成，L4 空列表/超长/设备不可用，
L5 无；**并发：并行 embed 调用串行化锁**）。

### S4 索引任务状态机（D8）

范围：run_index_task + outbox 路由 + arq/sync 双执行器 + 索引 API。
产出：`document_service.py` 修改、`sync_executor.py`、`arq_worker.py`、
`kb_indexing.py`（索引部分）。
验收：解析成功自动触发索引；手动重索引；失败不污染解析状态；
重跑幂等（旧块先清再插）；outbox 并发认领不重复。
测试：M28（L1 状态机迁移，L2 解析→索引链路 + Outbox，L3 手动触发，
L4 并发触发/重复触发 409/worker 中断恢复，L5 越权触发；
**并发：并发索引同一文档、并发 outbox 认领**）。

### S5 BM25（D4）

范围：分词 + 增量统计 + 打分 + 重建。
产出：`app/services/indexing/bm25.py`、kb_bm25_stats 读写。
验收：标准号/元素符号/数值分词正确；统计增量正确；删除回退正确；
查询打分排序合理；并发索引与重建一致。
测试：M29（L1 分词/统计/打分，L2 入库→检索全链路，L4 空语料/单块/超长查询，
L5 无；**并发：并发索引+重建一致性**）。

### S6 检索服务与 API（D6）

范围：检索服务 + rerank 占位 + 检索 API + schemas。
产出：`app/services/indexing/{retrieval,reranker}.py`、`kb_indexing.py` 检索部分。
验收：双向量+BM25+RRF 结果正确；filters 生效；RLS 生效；
召回评测（test_doc 样本，命中率/MRR）达到基线（本期 ≥0.7 命中率，后续与抽取/问答联动再调优）。
测试：M30（L1 融合打分，L2 种子数据检索集成，L3 API 功能，
L4 空查询/无块/超长/未知 kb，L5 越权检索与 API Key 作用域；
**并发：并行检索**）。

### S7 前端向量搜索 + 全链路验收

范围：向量搜索页 + 帮助文档 + 整体验收。
产出：`KbVectorSearchPage.tsx`、`api/modules/indexing.ts`、帮助文档更新。
验收：搜索交互（输入/过滤/结果/空态/错误态）、菜单权限、移动端可用；
S1-S7 全量回归 + 覆盖率统计表归档 `qa/results/`。
测试：M31 + M32（L1-L5 汇总，含 E2E 与整体并发/越权回归）。

### 阶段依赖

```
S1 ──► S2 ──► S4 ──► S6 ──► S7
               ▲      ▲
S3 ────────────┘      │
S5 ───────────────────┘
```

## 12. 开放确认点（默认按推荐实施，有异议请指出）

| # | 事项 | 推荐 | 说明 |
|---|------|------|------|
| X1 | 索引触发 | 解析成功后**自动入队** + 手动重索引 | D8 独立阶段，自动不阻塞解析 |
| X2 | BGE-M3 权重 | 需网络下载至 `models/bge-m3`（约 2.2GB fp32） | 若环境无网需提供离线权重 |
| X3 | 嵌入加载库 | 优先 transformers 直接实现；FlagEmbedding 仅回退 | 减少新增依赖；实测池化差异后再定 |
| X4 | BM25 统计粒度 | 按块计 df（沿用原版） | 与检索粒度一致 |
| X5 | 检索过滤 | 预留 document_id / has_table / level 过滤参数 | 本期实现，前端 S7 暴露 |
| X6 | text_chunks 冗余 | 与 document_chunks 并存（D5 已确认） | 向量表存检索字段，全文表存溯源元数据 |

## 13. 风险与缓解

| 风险 | 缓解 |
|------|------|
| BGE-M3 权重下载失败/网络受限 | 提供下载脚本与离线权重放置说明；embedding 失败时索引任务明确报错可重试 |
| pgvector HNSW 双索引写入放大 | 企业规模可控；S1 迁移后做性能基准（1 万块写入/检索 P95） |
| 增量 BM25 统计并发不一致 | kb_bm25_stats 行级锁 + version 乐观锁；并发测试覆盖 |
| 自动触发索引导致队列积压 | outbox 限流 + arq max_jobs；解析与索引并发参数独立配置 |
| 表格增强文本过长 | 沿用原版限制（前 15 行、数值列统计），超出截断入 content_for_embedding |

