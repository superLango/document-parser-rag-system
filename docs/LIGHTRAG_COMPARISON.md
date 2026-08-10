# LightRAG × document-parser-rag-system 全方位对比

> 基线：
> - **LightRAG**（最新代码，浅克隆，只读参考）：`lightrag/`，
>   提交 `419aaab3bd1aa13ab2c3a837b576e522e19e027f`（2026-08-10），MIT License，
>   论文 arXiv 2410.05779。
> - **document-parser-rag-system**（冻结基线，只读参考）：`document-parser-rag-system/`，
>   主分支 `d30c247`，垂直领域文档智能解析与 RAG 平台。
> - 本文所有结论均来自两份代码/文档的源码核对，未发现的内容明确标注“未找到”。

## 1. 定位差异（一句话）

| 项目 | 定位 |
|------|------|
| LightRAG | **通用 RAG 库 + 可选 API/WebUI**：面向任意文本的轻量级图检索增强生成，强调“简单、快速、可插拔存储、多查询模式”。 |
| document-parser-rag-system | **垂直领域文档智能产品**：面向航空材料检测等领域的“OCR → 版面重建 → 结构化抽取 → 术语标准化 → 知识图谱 → 混合问答”全链路，强调知识库隔离与领域配置。 |

两者并非同一层级的替代品：LightRAG 是可复用的 RAG 内核，原版是可独立部署的领域产品。

## 2. 技术栈对比

| 维度 | LightRAG | document-parser-rag-system |
|------|----------|----------------------------|
| 语言/版本 | Python ≥3.10 | Python 3.12（后端 venv 实测） |
| 核心形态 | 库（`lightrag_hku`）为主，API 为可选附加 | FastAPI 单体服务 + arq worker |
| API 框架 | FastAPI（`lightrag/api`，可选） | FastAPI 0.115+（全量） |
| 前端 | LightRAG WebUI：React + Radix + Sigma（图可视化）+ Vite | Vue 3 + TypeScript + reka-ui + Tailwind 4 + Cytoscape |
| 关系型存储 | PostgreSQL（可作一体化存储） | PostgreSQL（业务主库） |
| 向量存储 | Nano、Milvus、Qdrant、PG、Mongo、OpenSearch 可插拔 | Milvus（按 KB 分 Collection） |
| 图存储 | NetworkX（默认）、Neo4j、Memgraph、PG、Mongo、OpenSearch | NebulaGraph（按 KB 分 graph space） |
| 对象存储 | 文件系统/Mongo GridFS 等 | MinIO（按 KB 分 bucket） |
| 缓存/队列 | 进程内；无内置任务队列 | Redis db0 缓存 + db1 arq 任务队列 |
| LLM 接入 | OpenAI/Azure/Bedrock/Gemini/Ollama/vLLM 兼容等十余种 | 内网 vLLM（Qwen 系列），Ollama 兜底 |
| 嵌入/重排 | 可配置任意嵌入 + reranker | bge-m3 五维嵌入 + bge-reranker-v2-m3 |
| 文档解析 | 原生 markdown/pdf/docx/pptx/xlsx + MinerU/Docling 多模态服务 | GLM-OCR 主 + MinerU/PaddleOCR 备 + MinerU-Popo 后处理 |
| 评估/追踪 | RAGAS + Langfuse（README 2025.11 更新） | 未找到内置评估体系（仅 Prometheus 指标） |
| 认证/RBAC | 简单 JWT 账户 + API Key（`api/auth.py`） | 完整 RBAC + 审计 + IP 白名单 + 限流 |

## 3. 核心架构对比

### 3.1 LightRAG（库内核 + 薄服务层）

```
lightrag.py（LightRAG 编排类）
  ├─ parser（原生文档解析 / MinerU / Docling 多模态）
  ├─ chunker（Fix / Recursive / Vector / Paragraph 四策略）
  ├─ llm（角色化：EXTRACT / QUERY / KEYWORDS / VLM）
  ├─ kg（图+向量+文档+KV 四类存储，factory 按配置装配）
  │    ├─ graph：networkx / neo4j / memgraph / pg / mongo / opensearch ...
  │    ├─ vector：nano / milvus / qdrant / pg ...
  │    └─ doc_status / kv：pg / mongo / json ...
  ├─ pipeline（reservation 锁 + 阶段回滚 + 并发控制）
  ├─ prompts（实体/关系抽取、查询关键词、摘要、图结构化）
  └─ query：naive / local / global / hybrid / mix / bypass
```

关键设计：**图检索与向量检索双通道**。入库时既写向量又由 LLM 抽取实体/关系构建图；
查询时按模式组合“局部图子图检索 + 全局图摘要检索 + 向量语义检索”，最后统一生成。

### 3.2 原版（产品全链路）

```
API → 鉴权/RBAC → 知识库（六层隔离）
  ├─ 文档上传 → MinIO
  ├─ arq 异步任务：
  │    ├─ 阶段1：GLM-OCR → MinerU-Popo 版面重建 → 五维分块 → bge-m3 入库
  │    ├─ 阶段2-4：gliclass 类别过滤 → 五维混合检索 → LangExtract/BaseExtract 双轨抽取
  │    │     → 术语标准化 → 结果落盘
  │    └─ 图谱：实体关系抽取 → NebulaGraph 每 KB space
  ├─ RAG 问答：查询理解（意图/实体/重写/子查询）→ 五维+BM25+RRF+精排
  │     → LlamaIndex SubQuestion/Router 引擎 → SSE 溯源回答
  └─ 嵌入预览页（源 PDF + 抽取结果左右分栏）
```

关键差异：原版的差异化能力在**文档解析与结构化抽取**，LightRAG 的差异化能力在
**图检索算法与存储可插拔**。

## 4. 分块与索引对比

| 维度 | LightRAG | 原版 |
|------|----------|------|
| 分块策略 | 4 种可切换：Fix（固定 token）、Recursive（LangChain 递归字符）、Vector（语义分块）、Paragraph（段落语义，含 Smart Heading） | 五维分块（path/title/content/type/structural 五维向量字段），Markdown 结构重建后按结构分块 |
| 嵌入对象 | 文本块、实体、关系、文档摘要（同模型嵌入） | 五维向量字段独立嵌入（bge-m3） |
| 稀疏检索 | 未找到内置 BM25；依赖向量库全文能力 | 内置 BM25 稀疏 + RRF 融合 |
| 精排 | reranker 可配置（默认混合模式启用） | bge-reranker-v2-m3，可配置开关 |
| 增量 | 支持增量插入、文档删除后自动重建 KG | 支持任务化重建（`index_graph_tasks`），未见文档删除自动重建链路说明 |
| 重嵌入 | 不支持模型变更后自动重嵌入（README 明确提示） | 未找到重嵌入工具 |

## 5. 检索与问答对比

| 维度 | LightRAG | 原版 |
|------|----------|------|
| 查询模式 | naive / local / global / hybrid / mix / bypass；关键词抽取辅助 | 五意图路由：document_search / knowledge_graph / summarization / comparison / general |
| 图检索 | 局部：实体→邻居子图；全局：图摘要（LLM）；混合：两者叠加 | 图谱子图查询（NebulaGraph，max_hops）+ 意图路由到图引擎 |
| 复杂问题 | 混合模式自动组合 | 查询理解生成子查询 → LlamaIndex SubQuestion 并行子问答 |
| 溯源引用 | 支持 citation | 支持引用 + SSE 流式 |
| 上下文组装 | 块+实体+关系+图摘要按 token 预算裁剪 | 五维+BM25+RRF+精排后按 KB 配置组装 |

## 6. 知识图谱对比

| 维度 | LightRAG | 原版 |
|------|----------|------|
| 实体/关系抽取 | LLM 抽取 + gleaning 多轮补全 + 去重合并 | LLM 实体关系抽取 + 确定性 VID（md5(label:name)）upsert 去重 |
| 存储 | NetworkX 默认；Neo4j/Memgraph/PG/Mongo/OpenSearch 可选 | NebulaGraph 每 KB 独立 graph space（物理隔离） |
| 图-文关联 | chunk-entity 双向关联 + 文档-块-实体-关系四类存储 | 分块图谱服务（`chunk_graph_service`）关联文档与图 |
| 可视化 | WebUI 内置 Sigma 交互图谱 | 前端 Cytoscape 子图可视化 |
| 降级 | 存储异常视实现而定 | NebulaGraph 不可用返回空数据不 500（明确设计） |
| 更新 | 增量 insert + 删除重建 + 合并策略 | 重建任务 + KB 生命周期销毁 space |

## 7. 文档处理与多模态对比

| 能力 | LightRAG | 原版 |
|------|----------|------|
| PDF | pypdf 文本提取（不依赖 OCR 时） | GLM-OCR 整页 Markdown（方向/倾斜校正 + 版面分析 + 区域级识别） |
| 版面重建 | 原生解析器 + MinerU/Docling 外部服务 | MinerU-Popo：跨页表格合并、标题层级重建、图文关联、结构树 |
| Office | docx（含 Smart Heading）/pptx/xlsx（openpyxl） | 未找到 docx/pptx 直接解析服务（主走 OCR） |
| 表格 | markdown 表格解析（`_html_table`/`_markdown`） | 表格增强/清理 + Popo 表格合并 |
| 多模态 | RAG-Anything 合并：图、表、公式 | 图文关联（Popo），未见公式多模态链路 |
| 嵌入预览 | 未找到 | 源 PDF 内联预览 + 抽取结果分栏 |

## 8. 工程化与运维对比

| 维度 | LightRAG | 原版 |
|------|----------|------|
| 部署 | Docker Compose（full/lite/postgres）、Podman、K8s、setup wizard、gunicorn worker | 裸机 GPU 直跑 + start.sh；deploy/ 仅有 Milvus 配置，未找到完整容器编排 |
| 测试 | tests/ 覆盖 api/chunker/kg/llm/parser/pipeline/evaluation | 有 pytest 体系（旧版） |
| 可观测 | Langfuse 追踪 + RAGAS 评估 | Prometheus 指标 + structlog + trace_id |
| 安全 | 登录限流、body limit、admission 中间件、token subject 上限、bcrypt 时序均衡 | 慢速限流、IP 白名单、审计脱敏、RBAC |
| 文档 | 多语言 README + docs/ 丰富 | docs/ 含架构/部署/集成/配置，规模较小 |
| 依赖管理 | uv.lock + 多 requirements-offline | requirements.txt |

## 9. 优缺点总结

### 9.1 LightRAG 优点

1. **通用性与生态**：开源活跃、论文背书、PyPI 分发，社区迭代快（周级 feature 更新）。
2. **存储可插拔**：图/向量/文档/KV 四类存储抽象清晰，PG/Mongo/OpenSearch 可“一体化”，
   Milvus/Qdrant/Neo4j/Memgraph 可“专业拆分”，降低选型绑定。
3. **查询模式丰富**：local/global/hybrid/mix 与关键词抽取，覆盖“细节检索、全局总结、混合问答”。
4. **工程细节扎实**：pipeline reservation 锁、阶段回滚、并发控制、文档删除重建、
   角色化 LLM（EXTRACT/QUERY/KEYWORDS/VLM）、rerank 默认混合、RAGAS 评估 + Langfuse 追踪。
5. **多模态整合**：MinerU/Docling 服务接入、Smart Heading、office 解析，扩展性好。
6. **WebUI 图可视化**：React + Sigma 交互式图谱，直接可借鉴。
7. **安全细节**：登录限流、body limit、token 边界、bcrypt 时序均衡等，值得移植。

### 9.2 LightRAG 缺点

1. **默认存储不可生产**：默认是文件持久化内存库，README 明示仅限开发调试。
2. **领域结构化抽取缺失**：只有“实体/关系”通用抽取，没有 Schema 模板/Prompt 模板/术语集/
   Hook 这类可配置领域抽取体系。
3. **无 OCR 主链路**：纯文本/原生解析为主，中文扫描件需要外挂 MinerU/Docling，缺少
   GLM-OCR 区域级识别与版面后处理一体化。
4. **多租户/权限弱**：API 侧是简单账户 + API Key，没有知识库级 RBAC/RLS/审计。
5. **重嵌入成本高**：换嵌入模型需手工重建向量表，无工具化支持。
6. **token 级分块对表格/结构化文档弱**：Fix/Recursive 按 token 切分，破坏表格语义；
   Paragraph 策略依赖外部 NLP。
7. **超大图性能**：图检索全局模式依赖 LLM 摘要，成本与延迟高（未内置图数据库聚合优化）。
8. **中文领域适配**：Prompt 面向通用英文/开源 LLM，领域术语与标准号场景需自行改造。

### 9.3 原版优点

1. **全链路领域产品化**：上传 → OCR → 版面重建 → 五维索引 → 结构化抽取 → 术语标准化 →
   图谱 → 问答，业务闭环完整。
2. **知识库六层隔离 + RBAC**：PostgreSQL RLS / Milvus Collection / MinIO bucket /
   Nebula space / Redis 前缀 / 配置覆盖，安全边界是设计核心。
3. **配置驱动抽取**：Schema/Prompt 模板 + 术语集 + Hook 接口 + 双轨引擎（LangExtract 质量优先、
   BaseExtract 稳定优先），无硬编码回退。
4. **查询理解深入**：五意图分类、实体抽取、查询重写、子查询生成，加上 LlamaIndex 子问题/路由引擎。
5. **内网 GPU 直跑**：GLM-OCR、Qwen、bge-m3、reranker 全部本地化，数据不出网。
6. **工程化完整**：arq 任务队列、审计、导出、备份、Prometheus、trace_id、雪花 ID、嵌入预览页。
7. **降级策略明确**：图谱不可用、LLM 失败均有兜底，不阻塞主流程。

### 9.4 原版缺点

1. **技术栈绑定**：NebulaGraph/Milvus/MinIO 为强依赖，部署重、运维成本高。
2. **通用性弱**：领域模板仅 4 个（材料检测/医疗器械/合同/通用），换领域依赖模板建设。
3. **LLM 供应商单一**：主走内网 vLLM，缺乏多供应商抽象（有 Ollama 兜底但未见统一接口矩阵）。
4. **无内置评估体系**：未找到 RAGAS/评测集/指标闭环，效果改进靠人工。
5. **前端 Vue + 历史包袱**：代码量大，重构前维护成本高（当前重构版已换 React）。
6. **增量能力弱于 LightRAG**：图谱重建偏任务化，缺少“文档删除 → 自动重生成”等细粒度状态机。
7. **社区与文档规模小**：缺少 K8s/容器编排、setup wizard 等现代交付物。

## 10. 可借鉴清单（映射到重构版主流程）

### A. 直接借鉴（改动小、收益大）

| 借鉴项 | 来源 | 落地位置（重构版） |
|--------|------|--------------------|
| 查询模式扩展：在五意图基础上叠加 local/global/hybrid 双级图检索 | LightRAG `lightrag.py` 查询分支 | `backend/app/services/rag/`（迁移时） |
| 四类分块策略选择（Fix/Recursive/Vector/Paragraph） | `lightrag/chunker/*` | `backend/app/services/vector/chunker` |
| rerank 默认启用 + 混合模式 | LightRAG README/`rerank.py` | RAG 问答服务 |
| 文档删除自动重建 KG 的状态机 | LightRAG kg 重建实现 | `graph/index_graph_tasks` |
| RAGAS 评估 + 评测集目录 | `lightrag/evaluation`、`reproduce/` | `qa/evaluation/` |
| 登录限流/body limit/admission 中间件细节 | `lightrag/api/*middleware*` | 后端中间件 |
| WebUI 图谱交互（Sigma） | `lightrag_webui` | React 图谱页（现用 Cytoscape 方案可评估切换） |

### B. 吸收设计（需适配领域）

| 设计 | LightRAG 做法 | 我们的落地 |
|------|--------------|------------|
| 存储抽象 | 图/向量/文档/KV 四类 `Storage` 接口 | 在六层隔离不变的前提下抽出 `VectorStoreDriver` / `GraphDriver` 接口 |
| 角色化 LLM | EXTRACT/QUERY/KEYWORDS/VLM 独立配置 | 现有 `llm.engine` 增加角色维度 |
| Pipeline 并发/回滚 | reservation 锁 + 阶段提交 | arq 任务增加阶段状态机与回滚标记 |
| 全局摘要 | 图全局模式生成“图摘要”参与问答 | 增加 KB 级摘要缓存（可复用现有缓存服务） |
| 命名空间 | `namespace.py` 隔离工作区 | 与 KB 隔离合并（已具备，可对照补强） |

### C. 不建议照搬

1. **默认文件/内存存储**：生产必须走 PG/Milvus/Nebula。
2. **通用实体/关系抽取替代领域抽取**：我们保留 Schema/Prompt/术语集/Hook 体系，
   LightRAG 的抽取仅作为“通用图谱”备选通道。
3. **token 级分块替代结构分块**：表格/标准文档仍需五维结构分块。
4. **LightRAG 的简单 RBAC**：继续使用已完成的双层 RBAC + 资源 ACL。

## 11. 迁移建议（主流程阶段）

1. **以原版主流程为迁移基线**（领域抽取/OCR/隔离是护城河），LightRAG 只做“参考与对照基线”。
2. 迁移顺序建议：知识库/文档上传 → OCR+重建 → 五维索引 → 结构化抽取 → 图谱 → RAG 问答；
   每个阶段先把 LightRAG 的可借鉴项落到 `docs/` 设计再编码。
3. 建立 `qa/evaluation/` 评测集：复用 LightRAG 的 RAGAS 接入方式，对“领域问答 + 抽取质量”双指标回归。
4. 部署层补 Docker Compose/K8s（LightRAG 的 `k8s-deploy/`、`docker-compose*.yml` 可作模板）。
5. 保持内网 GPU 直跑与数据不出网约束；多供应商 LLM 抽象仅在领域推理层做适配器。

## 12. 结论

- **通用能力**：LightRAG 全面优于原版（存储可插拔、查询模式、增量、评估、部署物）。
- **领域能力**：原版全面优于 LightRAG（OCR→版面→结构化抽取→术语→隔离→审计）。
- **最佳路径**：以原版为领域主流程基线，系统性吸收 LightRAG 的图检索模式、分块策略、
  增量状态机、评估体系与部署模板；不做内核替换。
