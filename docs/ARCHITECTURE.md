# 系统架构文档

> 本文档描述 HansonDOC RAG 的整体架构、分层设计、六层知识库隔离机制、核心数据流与关键模块实现。

---

## 目录

1. [架构总览](#1-架构总览)
2. [分层设计](#2-分层设计)
3. [六层知识库隔离](#3-六层知识库隔离)
4. [核心数据流](#4-核心数据流)
5. [核心模块设计](#5-核心模块设计)
6. [异步任务架构](#6-异步任务架构)
7. [安全架构](#7-安全架构)
8. [可观测性](#8-可观测性)

---

## 1. 架构总览

HansonDOC RAG 采用**分层 + 异步任务**架构，以知识库（KB）为隔离边界，将结构化抽取与 RAG 问答统一在同一平台。系统采用**裸机 + GPU 直跑**部署模式：AI 推理服务（vLLM）与应用服务直接运行于宿主机以充分利用 GPU 显存，基础设施服务（数据库/向量库/对象存储/图数据库）原生或容器化运行。

```
┌─────────────────────────────────────────────────────────────────┐
│              前端层 (Vue 3 + TypeScript + reka-ui + Tailwind 4)    │
│  登录 │ 知识库列表 │ 文档管理 │ 抽取配置 │ 术语集 │ 图谱 │ 问答 │ 嵌入预览 │
└──────────────────────────────┬──────────────────────────────────┘
                               │ RESTful API (统一响应体 + trace_id)
┌──────────────────────────────▼──────────────────────────────────┐
│              API 网关层 (FastAPI + slowapi 限流)                   │
│        路由 │ JWT 鉴权 │ RBAC │ IP 限流 │ CORS │ GZip │ 链路追踪    │
└──────────────────────────────┬──────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────┐
│            核心业务层 (FastAPI + Pydantic + SQLAlchemy async)      │
│   文档管理 → OCR 解析 → 五维索引 → 结构化抽取 → 术语标准化 → 图谱  │
└──────────────────────────────┬──────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────┐
│              异步任务层 (arq + Redis database=1)                   │
│   一体化编排 │ OCR+向量入库 │ 结构化抽取 │ 图谱构建 │ 缓存预热 │ 清理 │
└──────────────────────────────┬──────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────┐
│              RAG 检索与问答引擎层                                  │
│  五维混合检索(Dense+BM25+RRF) → 重排 → 上下文组装 → LLM生成 → 溯源 │
└──────────────────────────────┬──────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────┐
│              数据持久层 (六层 KB 隔离)                             │
│  PostgreSQL(RLS) │ MinIO(分bucket) │ NebulaGraph(分space)        │
│  Milvus(分Collection) │ Redis(key前缀) │ 三层配置覆盖             │
└──────────────────────────────┬──────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────┐
│              AI 推理引擎层 (GPU 加速, 裸机直跑)                    │
│  GLM-OCR(9977) │ Qwen3.6-35B(9988) │ bge-m3五维 │ bge-reranker   │
│  MinerU-Popo │ gliclass │ MinerU/PaddleOCR(备)                    │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. 分层设计

### 2.1 前端层

- **框架**：Vue 3.5 组合式 API + TypeScript 严格模式
- **UI**：reka-ui（无样式可访问组件库）+ Tailwind CSS 4，自定义设计系统
- **状态**：Pinia 状态管理，axios 统一 HTTP 封装（自动注入 JWT + trace_id）
- **页面分组**：
  - `Kb/`：知识库工作区（文档管理、抽取配置、术语集、图谱、问答）
  - `Settings/`：系统设置
  - `admin/`：管理后台
  - `embed/`：免登录嵌入预览页面（左右分栏：源 PDF + 抽取结果）
  - `error/`：错误页
- **特殊处理**：`/embed/` 路径下 401 静默处理，不重定向登录页

### 2.2 API 网关层

- **框架**：FastAPI 0.115，所有路由挂载于 `/api/v1` 前缀
- **鉴权**：JWT Bearer Token（access + refresh 双令牌）
- **权限**：RBAC，4 角色（owner/admin/editor/viewer）+ is_superuser 超管
- **限流**：slowapi，区分默认限流（60/min）、上传限流、AI 限流
- **中间件链**：CORS → GZip → API 版本 → IP 白名单 → trace_id → 限流
- **统一响应**：`{code, message, data, trace_id}`，全局异常处理器统一格式

### 2.3 核心业务层

按领域拆分为 8 个服务子目录：

| 子目录 | 职责 |
|--------|------|
| `ocr/` | OCR 引擎抽象（GLM-OCR/MinerU/PaddleOCR）、文件管理、配置 |
| `popo/` | MinerU-Popo 后处理（normalizer/tree_builder/markdown_renderer/popo_inference） |
| `vector/` | 五维嵌入、五维向量存储、BM25 稀疏、分块、重建、表格增强 |
| `extraction/` | 抽取管线（extraction_pipeline）、检索服务（retrieval_service） |
| `extraction_config/` | 配置默认值、完整性校验、配置解析、快照 IO |
| `graph/` | NebulaGraph 存储、实体抽取、分块图谱 |
| `rag/` | RAG 服务、查询引擎、查询服务 |
| `llm/` | vLLM 大模型封装（生成/JSON/流式） |
| `embedding/` | 嵌入服务与配置 |
| `term/` | 术语集服务 |
| `kb/` | 知识库生命周期、配置加载、领域模板、备份 |
| `infra/` | 存储(MinIO)、缓存(Redis)、通知、导出、仪表盘、问答历史 |

### 2.4 异步任务层

- **队列**：arq + Redis（database=1 专用于任务队列，与 db0 缓存隔离）
- **任务类型**：一体化编排、OCR+向量入库、结构化抽取、图谱构建、缓存预热、清理
- **模式**：后台任务 + 轮询（非阻塞 SSE），结果落库，页面退出再进入可恢复

### 2.5 数据持久层

采用六层知识库隔离（详见 [第 3 节](#3-六层知识库隔离)）。

### 2.6 AI 推理引擎层

| 服务 | 端口 | 模型 | 用途 |
|------|------|------|------|
| vLLM | 9988 | Qwen3.6-35B-A3B-FP8 | 主 LLM（抽取 + 问答） |
| vLLM | 9977 | GLM-OCR | 主 OCR |
| 本地加载 | - | bge-m3 | 五维嵌入 |
| 本地加载 | - | bge-reranker-v2-m3 | 精排（可配置开关） |
| 本地加载 | - | gliclass-multilang-mini | 零样本类别分类 |
| 本地加载 | - | MinerU-Popo | 版面后处理 |

---

## 3. 六层知识库隔离

合规优先的**物理隔离**设计，每个知识库（KB）在所有存储层独立隔离，互不可见。

### 3.1 PostgreSQL — 行级安全（RLS）

- **策略**：单库 + `kb_id` 列 + RLS 行级安全策略
- **激活**：`SET LOCAL app.current_kb = '<kb_id>'` 激活当前 KB 的 RLS
- **强制**：DB 层强制过滤，superuser 可绕过（应用层额外显式 `kb_id` 过滤做纵深防御）
- **实现**：`app/api/deps.py` 的 `activate_rls(db, kb_id)` 与 `get_kb_context`

### 3.2 Milvus — 按 KB 分 Collection

- **命名**：`doc_chunks_{kb_id_hex}` + `doc_five_dim_{kb_id_hex}`（完整 32 位 hex）
- **隔离**：物理 Collection 隔离，删除 KB 即删除 Collection
- **检索**：通过 `expr=f'doc_id == "{doc_id}"'` 限定文档范围

### 3.3 MinIO — 按 KB 分 bucket

- **命名**：`kb-{kb_id}`
- **凭证**：每个 KB 独立 IAM 密钥，存于 `knowledge_buckets` 表
- **路由**：`storage_service` 的 `kb_id` 参数路由到专属 bucket

### 3.4 NebulaGraph — 按 KB 分 graph space

- **命名**：`kb_{kb_id_hex}`
- **驱动**：nebula-python（替代 neo4j），nGQL（替代 Cypher）
- **隔离**：原生多 graph space 物理隔离，无需 Enterprise 授权
- **DDL 异步生效**：CREATE SPACE/TAG/EDGE/INDEX 后需轮询等待，LOOKUP 可能报 "Schema not exist"，需重试机制（3 次 × 2 秒间隔）

### 3.5 Redis — key 前缀 + ACL

- **命名**：`kb:{kb_id}:` 前缀
- **隔离**：单实例 + key 前缀（不分 db，容量无限）+ ACL 用户
- **db 分配**：db0 缓存，db1 arq 任务队列

### 3.6 配置 — 三层覆盖

```
全局 settings (.env)  →  KB config JSON  →  Hook 脚本
       ↓                      ↓                  ↓
    引擎默认值            KB 自定义配置      运行时动态覆盖
```

- **全局**：`app/core/config.py` 的 `settings`（环境变量驱动）
- **KB 配置**：`kb_extraction_config` JSON（Schema/Prompt/术语集/LLM 端点）
- **Hook**：`kb_hooks/{kb_id}/hooks.py`，标准接口（extract_candidates/build_category_schema/validate_record/post_process/category_match/build_doc_info_prompt）

---

## 4. 核心数据流

### 4.1 一体化文档处理流程

公开一体化接口的端到端流程：

```
外部系统
   │ POST /public/extraction/upload (PDF)
   ▼
[public_upload]
   │ 1. 解析 KB ID（参数优先，否则 PUBLIC_KB_ID）
   │ 2. 校验文件大小/扩展名
   │ 3. 上传到 KB 专属 MinIO bucket
   │ 4. activate_rls + ensure_extraction_config_valid（配置完备性校验）
   │ 5. 创建 Document（process_status=queued）
   │ 6. 入队 arq: process_document_task（雪花 ID job_id）
   │ 7. 创建 Task 记录 + 回写 process_task_id
   ▼
返回 {task_id, document_id, status: "queued"}
   │
   │ （外部系统轮询 GET /public/extraction/{task_id}/status）
   ▼
[process_document_impl] arq 后台任务
   │
   ├─ 阶段1: OCR + Popo 重建 + 五维向量入库
   │   │ process_status = ocr_processing
   │   │ parse_document_impl:
   │   │   ├─ GLM-OCR 识别 → Markdown
   │   │   ├─ MinerU-Popo 后处理重建（结构树）
   │   │   ├─ 五维分块 + bge-m3 嵌入
   │   │   ├─ BM25 模型拟合（KB 级，先确保存在再插入）
   │   │   └─ 五维向量入库 doc_five_dim_{kb_id}
   │   ▼ process_status = extracting
   │
   ├─ 阶段2: 结构化抽取
   │   │ extract_document_impl:
   │   │   ├─ Phase 1: 文档大类识别
   │   │   ├─ Phase 2: 类别召回（gliclass 过滤 + 五维检索 + 置信度阈值）
   │   │   ├─ Phase 3: 上下文检索（五维混合 Dense+BM25+RRF + 重排）
   │   │   │   └─ 词法命中为空的类别直接跳过 LLM 调用
   │   │   ├─ Phase 4: LLM 抽取（LangExtract / BaseExtract 双轨）
   │   │   └─ 后处理（归一化 / 跨类校验 / 去重）
   │   ▼ 结果落库 structured_data.latest_result
   │
   ▼ process_status = completed
   │
   │ GET /public/extraction/{task_id}/result → 返回抽取结果 JSON
   │ GET /public/extraction/{task_id}/preview → 内联返回源 PDF
```

### 4.2 RAG 问答流程

```
用户提问
   │ POST /kbs/{kb_id}/qa/ask
   ▼
[query_service]
   │ 1. 查询理解（query_embedder 五维编码 + 术语精简）
   │ 2. 五维混合检索（Dense bge-m3 + Sparse BM25 + RRF 融合）
   │ 3. 重排序（bge-reranker-v2-m3，可配置开关）
   │ 4. 上下文组装（截断 + 最小保留字符保护）
   │ 5. LLM 生成（SSE 流式，带溯源引用）
   │ 6. 问答历史落库
   ▼
流式返回答案 + 来源引用
```

---

## 5. 核心模块设计

### 5.1 五维向量检索

区别于传统单维 Dense 检索，系统对每个文档块编码**五个维度的向量**，分别捕获不同语义特征：

| 维度 | 权重 | 捕获特征 |
|------|------|----------|
| path | 0.15 | 文档层级路径（章节定位） |
| title | 0.20 | 标题语义 |
| content | 0.45 | 正文内容（主权重） |
| type | 0.05 | 块类型（表格/数据结构） |
| structural | 0.15 | 结构化特征 |

- **存储**：单 Collection `doc_five_dim_{kb_id}`，5 个向量字段
- **检索**：每维独立检索 top_k，按权重 RRF 融合
- **混合**：稠密五维 + 稀疏 BM25 词法路，RRF 融合（`dense_weight=1.0, keyword_weight=1.2`）

### 5.2 双轨抽取引擎

| 引擎 | 特点 | 适用场景 |
|------|------|----------|
| **LangExtract** | output_schema 强约束 + 类别内并发 + few-shot 示例 | 质量优先，结构稳定 |
| **BaseExtract** | 短/长文本分流 + 分批串行 + 表格边界感知分批 | 稳定性优先，大模型友好 |

- **切换**：`llm.engine` 配置项
- **降级**：LangExtract 失败时可降级到 BaseExtract（`EXTRACTION_V3_EXTRACTION_FALLBACK_TO_GLMOCR`）
- **并发模型**：`inflight = cross_category × within_category`，需匹配 vLLM `--max-num-seqs`

### 5.3 术语集精简

Query 术语集的两层精简逻辑（`query_embedder.py`）：

1. **单条清洗**（`_refine_item_name`）：去括号内容、去"-方法X"后缀、strip 空白
2. **整体去重截断**（`_refine_items`）：过滤空值/纯代号 → 精确去重 → 字符级语义相似度去重（difflib.SequenceMatcher，阈值 0.85）

生成两套精简结果：`refined_short`（query_refined_limit）与 `refined_long`（query_main_limit），用于构建五维 query 文本。

### 5.4 BM25 稀疏向量

- **KB 级模型**：每个 KB 独立 BM25 模型，从该 KB 文档块语料拟合（存于 `data/bm25/{kb_id_hex}.json`）
- **重建流程**：向量入库阶段先显式确保 BM25 模型存在（缺失则用本次文档块语料拟合并持久化），再执行插入
- **编码**：jieba 分词 + BM25 算法，输出 Milvus `SPARSE_FLOAT_VECTOR`

### 5.5 知识图谱

- **存储**：NebulaGraph，每 KB 独占 graph space
- **抽取**：基于 LLM 的实体关系抽取（`entity_extractor.py`）
- **查询**：子图查询 + 可视化（前端 cytoscape.js）
- **降级**：NebulaGraph 不可用时 `graph_store.py` 返回空数据，不抛 500

---

## 6. 异步任务架构

### 6.1 任务清单

| 任务文件 | 任务 | 职责 |
|----------|------|------|
| `process_tasks.py` | `process_document_task` | 一体化编排（OCR + 抽取） |
| `document_tasks.py` | `parse_document_impl` | OCR + Popo 重建 + 五维向量入库 |
| `extraction_tasks.py` | `extract_document_impl` | 结构化抽取 |
| `index_graph_tasks.py` | 图谱构建 | 实体关系抽取 + Nebula 入库 |
| `prompt_cache_warmer.py` | 缓存预热 | 低峰期 Prompt 前缀缓存预热（cron） |
| `cleanup_tasks.py` | 清理 | 过期数据/临时文件清理 |

### 6.2 状态追踪

- **`Document.process_status`**：一体化流程状态（queued/ocr_processing/ocr_done/extracting/completed/failed），独立于 `Task.status`
- **原因**：`parse_document_impl` 完成时会把 `Task.status` 置 completed，`extract_document_impl` 又改回 running，导致抖动；读 `process_status` 避免抖动
- **恢复**：页面退出再进入，凭 task_id 查 `process_status` 恢复进行中状态或显示结果

### 6.3 任务 ID

- **雪花 ID**：非自增整数，不可顺序枚举，增强公开接口安全性

---

## 7. 安全架构

### 7.1 认证与授权

- **JWT 双令牌**：access token（默认 1440 分钟）+ refresh token（7 天，静默续期）
- **RBAC**：用户-知识库多对多 + 4 角色 + is_superuser 超管
- **显式成员制**：不设 is_public，必须加入成员才能访问

### 7.2 密码策略

- 最小长度 8，需含大小写字母 + 数字（特殊字符可选）
- 密码历史（禁止复用最近 5 个旧密码）+ 过期天数（默认 90 天）
- 登录失败锁定（5 次失败锁 30 分钟）

### 7.3 公开接口安全缓解

免鉴权方案的必要补充：

- **雪花 ID**：task_id 不可顺序枚举
- **IP 限流**：上传 10/min，查询 60/min
- **配置校验**：上传时 `ensure_extraction_config_valid` 校验 KB 抽取配置完备
- **RLS 处理**：查询接口凭 task_id 主键查询临时 `SET LOCAL row_security = off`（安全性由雪花 ID + 限流保证）

### 7.4 其他

- 管理端 IP 白名单（`/api/v1/admin/*`）
- CORS 来源控制（生产环境严格限定）
- 审计日志保留 90 天

---

## 8. 可观测性

### 8.1 指标

- **Prometheus**：`/metrics` 端点，HTTP 请求量/延迟/进行中数（`prometheus-fastapi-instrumentator`）
- **环境变量**：`ENABLE_METRICS` 控制启用

### 8.2 日志

- **structlog**：结构化日志，含 trace_id 链路追踪
- **trace_id**：请求头 `X-Trace-Id` 自动注入或生成，全链路关联

### 8.3 链路追踪

- 每个请求注入 `X-Trace-Id`，响应体 `trace_id` 字段返回
- 用于全链路日志关联与排障
