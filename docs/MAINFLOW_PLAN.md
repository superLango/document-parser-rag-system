# 主流程技术方案 V2（结合 LightRAG 与原版优点）

> 适用范围：RBAC 阶段（P0-P2）已完成后的主流程迁移（知识库 → 文档解析 → 索引 →
> 结构化抽取 → 图谱 → RAG 问答）。
> 本文档把用户已拍板的决策固化为架构基线；未拍板的内容给出深度对比与推荐，
> 最终以【决策清单】逐条确认。所有结论基于当前仓库源码与 LightRAG 克隆代码。

## 1. 目标与原则

1. **企业内部使用**：优先可靠性、可维护性、数据安全，不做通用多租户产品化。
2. **知识库 RLS 隔离为第一边界**：所有 KB 域数据（文档/分块/实体/关系/任务）都必须过 RLS。
3. **少组件、少运维**：能用 PostgreSQL 解决的存储一律进 PG，减少 Milvus/Nebula 等组件。
4. **任务不因网络/进程抖动丢单**：保留 Redis + 队列，但补齐事务性发单、幂等、重试、死信、心跳。
5. **领域能力保留**：OCR → 版面重建 → 五维/结构索引 → 配置驱动抽取 → 图谱 → 问答的闭环不变。
6. **吸收 LightRAG 通用能力**：LLM 兼容层、评估/追踪、查询模式、存储抽象思想，不做内核替换。

## 2. 已确定决策（D1-D10）

| 编号 | 决策 | 架构影响 |
|------|------|----------|
| D1 ✅ | KB RLS 隔离 + 企业内部使用 | 已确认：隔离层级为**知识库层级**，知识库为产品入口；所有 KB 表启用 RLS |
| D2 | 主库 PostgreSQL | 业务库 `hanson_doc_rag` 保持唯一关系库 |
| D3 | 向量库、图库改用 PostgreSQL | 引入 pgvector；图采用 PG 内方案（见 §4.3 对比） |
| D4 | 对象存储 MinIO | 每 KB 独立 bucket，保留现有 storage_service |
| D5 | 保留缓存/队列（Redis + arq）并强化健壮性 | 见 §4.5 队列优化清单 |
| D6 | LLM 接入使用 LightRAG 兼容体系 | 统一 LLM 客户端适配层（§5） |
| D7 | 嵌入/重排待三方比较 | 暂不选型，架构预留 embedder/reranker 接口（§9.1） |
| D8 | 文档解析自建：PDF-Extract-Kit 为底 + GLM-OCR 替换 | 见 §6 流水线 |
| D9 | 评估/追踪采用 LightRAG 完善方案 | RAGAS + Langfuse（§8） |
| D10 | 认证使用最新认证体系 | 双层 RBAC + 资源 ACL + API Key + 审计（已完成，直接复用） |

### 2.1 本轮 UI 决策（已确认）

1. **知识库为入口**：进入系统后知识库页为主入口之一，所有知识库以**卡片方式**展现（卡片含名称、描述、我的角色、成员数、创建时间、成员管理/删除操作）。
2. **新建知识库**：不再选择领域模板（移除 domain template 选择）；创建时可进行**初始成员管理**（按用户名 + 角色添加/移除，创建后批量发送邀请，失败项单独提示）。
3. 视觉遵循 UI_THEME/UI_INTERACTION 规范：卡片浮起、错峰入场、浅绿+白。

## 3. 目标总体架构

```
┌────────────────────────────────────────────────────────────────────┐
│ 前端 React（现有）                                                 │
│ 工作台 │ 知识库 │ 文档 │ 抽取配置 │ 术语集 │ 图谱 │ 问答 │ 预览      │
└───────────────┬────────────────────────────────────────────────────┘
                │ REST（统一响应体 + trace_id）
┌───────────────▼────────────────────────────────────────────────────┐
│ API 层：FastAPI（现有认证体系：RBAC/ACL/API Key/审计/限流）          │
│ 知识库上下文：activate_rls(app.current_kb) + 有效角色（成员∪群组）    │
└───────────────┬────────────────────────────────────────────────────┘
                │
┌───────────────▼────────────────────────────────────────────────────┐
│ 业务服务层                                                         │
│ 文档/OCR(自建) │ 版面重建 │ 分块索引(待定) │ 结构化抽取 │ 图谱 │ 问答 │
└───────────────┬────────────────────────────────────────────────────┘
                │ 事务性任务发单（Outbox）
┌───────────────▼────────────────────────────────────────────────────┐
│ 异步任务层：Redis(缓存+队列 arq) → PG 任务表（状态/重试/心跳/DLQ）   │
│ OCR 页面并发 │ 抽取类别并发 │ 图谱重建 │ 缓存预热                      │
└───────────────┬────────────────────────────────────────────────────┘
                │
┌───────────────▼────────────────────────────────────────────────────┐
│ 数据层（单一 PG + MinIO）                                          │
│ PostgreSQL 16：业务表(RLS) + pgvector(分块/实体/关系向量)            │
│               + 图邻接表(RLS) + 任务/审计/评估表                     │
│ MinIO：每 KB bucket（源文件/OCR中间件/抽取结果/预览）                 │
└───────────────┬────────────────────────────────────────────────────┘
                │
┌───────────────▼────────────────────────────────────────────────────┐
│ 推理层（内网 GPU）                                                 │
│ GLM-OCR（正文/表格/公式图片块）│ Qwen LLM（vLLM/Ollama 兼容）        │
│ 嵌入/重排（待三方比较）│ 可选公式兜底（UniMERNet 备选）              │
└────────────────────────────────────────────────────────────────────┘
```

## 4. 存储层详细方案

### 4.1 PostgreSQL 主库 + KB RLS（D1/D2）

- 保持现有 `users/roles/workspaces/kb_members/kb_group_access` 等表。
- 新增 KB 域表统一带 `kb_id`，全部 `ENABLE ROW LEVEL SECURITY`。
- 策略函数：
  - `app.current_kb()`：读取 `current_setting('app.current_kb', true)`。
  - `kb_effective_role(kb_id, user_id)`：直接成员角色 ∪ 群组授权角色取最高（复用 P2 并集逻辑，下沉为 SQL 函数）。
  - `kb_can(kb_id, role_level)`：按角色等级比较（owner>admin>editor>viewer）。
- 每个请求在 `get_kb_context` 中执行 `SELECT set_config('app.current_kb', ...)`，并设置 `app.user_id`、`app.is_superuser`。
- 超级管理员：策略中放行 `current_setting('app.is_superuser', true)='true'`。
- 服务层权限校验（现有 `require_role`/有效角色）作为**第一道闸**，RLS 作为**纵深防御**，避免误配导致越权。

### 4.2 向量存储：pgvector 替代 Milvus（D3）

#### 候选对比

| 方案 | 成熟度 | 索引 | 混合检索 | 运维 | 与 RLS 协同 | 结论 |
|------|--------|------|----------|------|-------------|------|
| **pgvector** | 官方生态、PG16 支持良好 | HNSW / IVFFlat；0.8+ 支持 halfvec/sparsevec、标量量化 | 与 FTS/trigram 同库 RRF | 零额外组件 | 表级 RLS 天然生效 | **推荐** |
| pgvecto.rs | 性能宣传好 | HNSW | 较好 | 独立扩展二进制，升级跟随风险 | 表级 RLS 可生效 | 备选 |
| pg_embedding（lantern） | 更新快 | HNSW | 一般 | 扩展依赖 | 可生效 | 备选 |
| 继续用 Milvus | 成熟、规模大 | 多种 | 强 | 额外集群/运维 | 需应用层过滤，无法 RLS | 不推荐（违背 D3） |

#### 推荐

- 选 **pgvector**（PG16 + pgvector 0.8+）。
- 表结构：分块表带 `embedding vector(N)`、`metadata jsonb`、`kb_id`；实体/关系表各自带向量列。
- 索引：HNSW（`vector_cosine_ops`）；实体/关系数量级小，可用 IVFFlat。
- 混合检索：`pgvector` 稠密 + `tsvector`/`pg_bigm` 稀疏 + RRF（沿用原版 RRF 权重），精排后接 LLM。
- 中文分词：zhparser 或 pg_bigm（2-gram）；推荐 pg_bigm（无需停用词表，模糊匹配好），如后续 BM25 需求复杂再评估 `pg_search`（ParadeDB）。
- 预留 `VectorStoreDriver` 接口，未来若数据量超单机 PG 再切专用向量库，业务代码不变。

### 4.3 图存储：PostgreSQL 内方案替代 NebulaGraph（D3）

#### 候选对比

| 方案 | 查询语言 | 多跳遍历 | RLS | 事务/备份 | 运维 | 适用规模 | 结论 |
|------|----------|----------|-----|-----------|------|----------|------|
| **关系邻接表 + 递归 CTE** | SQL | 1-N 跳可控（≤3 常用） | 节点/边表各自 RLS | 与业务同事务、pg_dump 一致 | 零扩展 | 数十万节点/百万边 | **推荐** |
| Apache AGE | openCypher | 好 | 策略需在 AGE 表上手工配置，与 PG 策略体系协同弱 | 支持 PG 事务，备份复杂一些 | 独立扩展（PG16 兼容需核对版本） | 大图 | 备选/适配器 |
| pgRouting | SQL 函数 | 路径算法 | 可 | 同 PG | 扩展 | 路径规划 | 不适合图谱问答 |
| 保留 NebulaGraph | nGQL | 最强 | 物理 space 隔离 | 独立备份 | 重 | 百万级以上 | 不推荐（违背 D3） |

#### 推荐

- **关系邻接表 + 递归 CTE**，理由：
  1. 企业内部 KB 图谱规模有限（单 KB 通常 ≤ 几十万节点），3 跳内子图 CTE 足够；
  2. 节点/边表都是普通 PG 表，**RLS 直接生效**（D1 硬性要求）；
  3. 与文档/分块同库同事务，抽取结果与图谱强一致；
  4. 无扩展依赖、pg_dump 备份简单。
- 表设计：`graph_entities(kb_id, entity_key, label, properties jsonb, embedding)`、
  `graph_relations(kb_id, source_key, target_key, rel_type, properties, embedding)`，
  联合唯一键 `(kb_id, entity_key)` / `(kb_id, source, target, rel_type)`（沿用原版确定性 VID 思想，改为业务键）。
- 多跳查询：递归 CTE（`WITH RECURSIVE`）+ 深度限制 + 关系类型过滤 + 每跳 RLS。
- 保留 `GraphStore` 接口（现 `graph_store.py`），内部实现换成 PG；未来如确有 Cypher 需求可加 Apache AGE 适配器而不改业务层。
- 图可视化：前端继续 Cytoscape 或评估切换 react-sigma（LightRAG WebUI 方案），后端只返回子图 JSON。

### 4.4 MinIO（D4）

- 每 KB 一个 bucket（`kb-{id}`），对象键：`originals/`、`ocr/`、`extract/`、`preview/`、`cache/`。
- 现有 `storage_service` 保留；增加：
  - 预签名 URL（上传/预览/下载），有效期可配置；
  - 生命周期规则（临时中间件 7 天清理）；
  - 任务幂等：MinIO 对象键 = `task_id/文件名`，重复执行覆盖且校验 ETag。
- 不把 MinIO 数据放 PG（二进制大对象仍走对象存储），PG 只存元数据。

### 4.5 缓存/队列健壮性优化（D5）

#### 为什么继续 arq + Redis（对比）

| 方案 | 异步原生 | 与 asyncpg/FastAPI 协同 | 重试/延迟 | 运维 | 结论 |
|------|----------|------------------------|-----------|------|------|
| arq | 是（asyncio） | 最优 | 内置 retry/defer | 轻 | **推荐（保留）** |
| Celery | 否（同步为主） | 一般 | 强 | 重 | 不换 |
| Dramatiq | 否 | 一般 | 强 | 中 | 不换 |
| RQ | 否 | 一般 | 弱 | 轻 | 不换 |

#### 健壮性改造清单（新方案）

1. **事务性发单（Outbox）**：业务事务内写 `task_outbox`（PG），Redis 仅做信号；独立 dispatcher 把 outbox 入队 arq。解决“业务已提交但 Redis 断连丢任务”。
2. **幂等**：`task_id`（雪花 ID）作为 arq job id；重复投递时 Redis SETNX 去重；任务内所有副作用（MinIO 上传、向量/图 upsert、抽取结果）均幂等。
3. **重试与死信**：arq `max_tries` + `retry_delay` 指数退避；超限进入 `task_dead_letter`（PG），管理员可查看/重放。
4. **心跳与超时回收**：任务表记录 `heartbeat_at`；worker 定期上报；超时未心跳的 job 标记 failed/重新调度，防止进程被杀后永久悬挂。
5. **并发控制**：全局信号量 + 按 KB/类型限流（OCR 页面并发、抽取类别并发沿用原版参数），避免打爆 vLLM/GLM-OCR。
6. **阶段状态机**：`queued → ocr_processing → ocr_done → indexing → extracting → graph → completed / failed`，与现有 process_status 兼容；每阶段结束写 checkpoint，支持断点续跑。
7. **Redis 降级**：缓存可用则用；Redis 不可用时任务入口返回 503 并保留 outbox（不丢单），恢复后自动补发。
8. **监控**：arq 任务指标进 Prometheus，心跳延迟/死信数告警。

## 5. LLM 兼容层（D6）

### 设计（吸收 LightRAG `lightrag/llm/*` 体系）

- 定义统一接口 `LLMClient`：
  - `complete(messages, json_mode, temperature, max_tokens)`
  - `embed(texts)`（预留，接入待选嵌入模型）
  - `rerank(query, docs)`（预留）
- 内置实现（移植 LightRAG 的适配器思想，按需裁剪）：
  - `OpenAICompatibleClient`：覆盖 vLLM / Ollama / LMDeploy / 兼容网关（主路径）；
  - `OllamaClient`、`GeminiClient`、`BedrockClient` 等作为可选实现；
- **角色化配置**（LightRAG EXTRACT/QUERY/KEYWORDS/VLM 四角色）：
  - EXTRACT：结构化抽取 + 实体关系抽取；
  - QUERY：问答生成 + 查询理解；
  - KEYWORDS：关键词/意图（可跳过）；
  - VLM：图文理解（未来多模态）。
  - 每个角色独立 endpoint/model/超时/并发，配置放 KB config 与系统配置双层。
- 工程要求：超时、重试（指数退避）、JSON 模式（`generate_json` 兼容）、失败降级（原版 query_service 已有兜底）、并发信号量。
- 替换点：现有 `llm_service.py` 收敛为兼容层门面，业务代码不再直接拼 endpoint。

## 6. 文档解析自建流水线（D8）

### 设计原则

以 PDF-Extract-Kit 为底层框架（保留其 PDF→图片、页眉页脚擦除、DocLayout-YOLO 版面分析、阅读顺序、Markdown 拼装），
把“公式/表格/正文识别”统一拦截改为调用 **GLM-OCR**。

### 流水线

```
PDF
 ├─[保留] PDF→高清图片（页面级，dpi 可配置）
 ├─[保留] 页眉页脚擦除（规则 + 版面框过滤）
 ├─[保留] DocLayout-YOLO 版面分析 → 版面框（标题/正文/表格/公式/图/页眉页脚）
 ├─[保留] 阅读顺序排序
 ├─[保留] Markdown 拼接拼装（含标题层级、列表、代码块）
 ├─[替换] 按版面框裁剪局部图片块
 │    ├─ 正文块 ────────→ GLM-OCR（替代 PaddleOCR）
 │    ├─ 表格块 ────────→ GLM-OCR（替代 StructEqTable）
 │    └─ 公式块 ────────→ GLM-OCR（替代 UniMERNet；可选保留 UniMERNet 作公式兜底）
 └─[可选/增强] MinerU-Popo 后处理（跨页表格合并、标题重建、图文关联）→ 结构化 Markdown
```

### 拦截实现（对应 D8“统一重写拦截/剔除”）

- 在 PDF-Extract-Kit 的“推理结果分派”处增加 `OCRBackend` 接口：
  - `ocr_block(image, block_type) -> markdown_fragment`；
  - 默认实现 `GLMOCRBackend`：把裁剪图块 POST 到 GLM-OCR（9977），返回 Markdown 片段；
  - 原 PaddleOCR/UniMERNet/StructEqTable 分支不再注册（或保留为 `legacy` 配置开关，默认关闭）。
- 并发：页面并行（max 4）+ 块并行（max 8），GLM-OCR 侧限流；失败块重试 2 次，仍失败标记 `ocr_failed` 不阻塞整页。
- 输出：页面 Markdown + 版面 JSON（bbox/type/order）→ 进入索引与抽取阶段。
- 风险与兜底：
  - 公式精度：GLM-OCR 对公式的 LaTeX 还原可能弱于 UniMERNet → 配置 `FORMULA_FALLBACK=unimernet` 可选；
  - 表格：GLM-OCR 表格 Markdown 良好，但复杂跨页表仍需 Popo 合并；
  - 中文横排/竖排：沿用原版方向/倾斜校正预处理。

## 7. 认证与权限（D10）

- 直接复用当前认证体系：双层 RBAC（系统角色）+ 资源 ACL（KB/工作空间）+ API Key + 审计。
- 主流程新增端点统一走 `require_permission` / `require_not_pending` + `get_kb_context`（RLS 激活）。
- API Key 对 KB 接口生效（scopes 交集），满足企业脚本/集成需求。
- 审计覆盖：上传、OCR、抽取、图谱、问答等敏感动作全部留痕。

## 8. 评估与追踪（D9）

### 追踪（Langfuse）

- 集成点：查询理解 → 检索（向量+BM25+RRF）→ 精排 → LLM 生成，各阶段 span；
- 记录：query、retrieved chunk ids、rerank score、prompt/response、token 用量、延迟；
- 企业内网部署：Langfuse 自托管（PG 存储），数据不出网。

### 评估（RAGAS）

- 评测集：`qa/evaluation/datasets/`（领域问答对 + 期望引用文档）；抽取质量集（Schema 字段 F1）；
- 指标：
  - RAG：faithfulness、context precision、context recall、answer relevancy；
  - 检索：命中率、MRR、召回@k；
  - 抽取：字段级精确率/召回率/F1、术语标准化一致率；
- 发布门禁：每次主流程改动跑评估，指标回退即失败（纳入铁律测试流程）。

## 9. 待定决策与对比框架（等待逐条确认）

### 9.1 嵌入与重排（D7：暂缓，三方比较后决定）

需要比较的三方（待你确认是否按此范围）：
1. **bge-m3**（原版现行：五维嵌入 + 重排 bge-reranker-v2-m3）；
2. **LightRAG 社区常用组合**（如 OpenAI/Gemini 嵌入 + reranker 或 Qwen3-Embedding）；
3. **国产开源替代**（如 Qwen3-Embedding、GTE、Conan-embedding 等）。
比较维度：中文领域效果、维度与 pgvector 索引适配、重排质量、GPU/显存占用、许可证、部署复杂度。
结论前，架构上只预留 `embedder`/`reranker` 接口，不写死模型。

### 9.2 分块与索引（暂缓，后续比较）

需要比较的候选：
1. 原版五维结构分块（path/title/content/type/structural）；
2. LightRAG 四策略（Fix / Recursive / Vector / Paragraph）；
3. 混合：结构分块为主 + 段落语义分块备选。
比较维度：表格/标准文档保真、检索召回、抽取上下文质量、token 成本、实现成本。
结论前，索引层只预留 `chunker` 接口与 `chunk schema`，不落具体策略。

### 9.3 其他待定（本文给出推荐，待确认）

| 编号 | 事项 | 推荐 | 说明 |
|------|------|------|------|
| O1 | 混合检索组合 | pgvector 稠密 + pg_bigm 稀疏 + RRF（精排可配） | 替代 Milvus+BM25 原组合，同库实现 |
| O2 | 图查询深度 | 默认 ≤3 跳，可配置 | 企业 KB 规模足够 |
| O3 | 公式兜底 | 默认 GLM-OCR，配置项可开 UniMERNet | 平衡依赖与精度 |
| O4 | 部署形态 | 裸机 GPU + Docker Compose（PG/MinIO/Redis/Langfuse） | 保留内网直跑，降低运维 |
| O5 | 评测集范围 | 先建 50 条领域问答 + 30 份抽取样例 | 可评审后扩充 |
| O6 | 任务并发参数 | OCR 页并发 4、块并发 8、抽取类别并发沿用原版 | 按 GPU 实测调整 |
| O7 | API Key 是否覆盖 KB 接口 | 覆盖（scopes 交集） | 企业集成需要 |
| O8 | 多模态（图片/音频） | 本期不做，预留 VLM 角色 | LightRAG RAG-Anything 能力后置 |

## 10. 数据模型草案（核心表）

```
knowledge_bases（现有，+RLS 相关字段）
documents(kb_id, task_id, file_meta, status, ocr_md, layout_json, deleted_at)  [RLS]
chunks(kb_id, doc_id, seq, content, path/title/type/structural 字段,
       embedding vector(N), bm25_text tsvector, metadata jsonb)               [RLS]
graph_entities(kb_id, entity_key, label, properties jsonb, embedding)          [RLS]
graph_relations(kb_id, source_key, target_key, rel_type, properties, embedding)[RLS]
extraction_records(kb_id, doc_id, category, feature, value, confidence)         [RLS]
tasks(kb_id, task_id, type, status, attempts, heartbeat_at, error, checkpoints) [RLS]
task_outbox(id, task_id, type, payload, created_at, enqueued_at)               [全局]
task_dead_letter(id, task_id, error, attempts, created_at)                     [全局]
evaluation_runs / eval_results（全局，管理员可见）
```

- 所有 KB 表 `ENABLE RLS`，策略引用 §4.1 的函数。
- `graph_entities/graph_relations` 同时承载向量列（实体/关系语义向量），满足“图+向量同库”。

## 11. 实施路线（每阶段按铁律测试）

| 阶段 | 内容 | 关键产出 |
|------|------|----------|
| M1 | PG 存储底座：pgvector 扩展、RLS 策略函数、GraphStore 换 PG、MinIO 键规范 | 迁移脚本 + RLS 集成测试 |
| M2 | 任务健壮化：outbox、幂等、重试/死信、心跳 | 故障注入测试（杀 worker/断 Redis） |
| M3 | LLM 兼容层 + 角色化配置 | 多供应商适配测试 |
| M4 | 文档解析自建流水线（PDF-Extract-Kit + GLM-OCR 拦截） | 页面级/块级并发与兜底测试 |
| M5 | 分块与索引（待定后落地） | 检索评测 |
| M6 | 结构化抽取迁移（Schema/术语集/Hook/双轨） | 抽取质量评测 |
| M7 | 图谱迁移（实体关系抽取 → PG 图 + 子图查询） | 图谱评测 |
| M8 | RAG 问答（查询理解 + 混合检索 + RRF + 精排 + 溯源/SSE） | RAGAS 评测 |
| M9 | 评估/追踪接入（Langfuse + RAGAS 门禁） | 评测流水线 |

## 12. 风险与缓解

| 风险 | 缓解 |
|------|------|
| pgvector 在超大规模下性能下降 | 企业规模可控；预留 VectorStoreDriver 可切专用库 |
| 递归 CTE 深图慢 | 限制跳数、物化高频子图、边类型索引 |
| GLM-OCR 替换公式/表格识别精度下降 | 可选 UniMERNet/StructEqTable 兜底，评测对比 |
| Redis 断连 | outbox + 503 + 自动补发，任务不丢 |
| LLM 多供应商配置复杂度 | 角色化 + 每角色独立配置 + 兼容层收敛 |
| 迁移风险（旧数据） | 按 KB 分批迁移 + 评估门禁 + 可回滚 |

## 13. 决策清单（请逐条确认）

| 序号 | 待确认项 | 推荐 |
|------|----------|------|
| Q1 | 向量库选型 | pgvector（0.8+，HNSW） |
| Q2 | 图存储选型 | 关系邻接表 + 递归 CTE（预留 AGE 适配器） |
| Q3 | 稀疏检索 | pg_bigm + tsvector + RRF |
| Q4 | 队列健壮化 | arq + Outbox + 幂等 + 死信 + 心跳（按 §4.5） |
| Q5 | LLM 兼容层范围 | OpenAI 兼容（vLLM/Ollama/LMDeploy）优先，Gemini/Bedrock 可选 |
| Q6 | 公式兜底 | 默认 GLM-OCR，配置可开 UniMERNet |
| Q7 | 任务并发参数 | OCR 页 4 / 块 8 / 抽取沿用原版（按 GPU 实测调整） |
| Q8 | 评估指标集 | RAGAS 四指标 + 检索命中/MRR + 抽取字段 F1 |
| Q9 | 部署形态 | 裸机 GPU + Docker Compose 附属组件 |
| Q10 | 多模态范围 | 本期不做，预留 VLM |
| Q11 | 嵌入模型三方比较 | 按 §9.1 范围推进（待你确认范围） |
| Q12 | 分块索引比较 | 按 §9.2 候选推进（待你确认范围） |
