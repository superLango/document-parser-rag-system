# Tasks — 文档智能解析与RAG系统开发

任务按8个阶段组织，前置阶段完成后再进入下一阶段。同一阶段内标注 `[可并行]` 的子任务可并行执行。

---

## 阶段0：项目脚手架与基础设施

- [x] Task 0.1: 创建项目顶层目录结构（`frontend/`、`backend/`、`deploy/`、`docs/`、`scripts/`）与 `.gitignore`（排除 `venv/`、`volumes/`、`models/`、`node_modules/`、`.env`）
- [x] Task 0.2: 编写 `deploy/docker-compose.yml` 基础设施编排（PostgreSQL、Redis、MinIO、Neo4j、Milvus 依赖 etcd），使用 `deploy/docker-compose.override.yml` 区分开发环境
  - [x] SubTask 0.2.1: PostgreSQL 15-alpine + 初始化脚本 `scripts/init_db.sql`
  - [x] SubTask 0.2.2: Redis 7-alpine + `deploy/redis.conf`
  - [x] SubTask 0.2.3: MinIO + bucket 初始化脚本
  - [x] SubTask 0.2.4: Neo4j 5 + APOC 插件
  - [x] SubTask 0.2.5: Milvus 2.4 standalone + etcd
- [x] Task 0.3: 编写 `deploy/nginx.conf`（前端静态资源 + API代理 + SSE/WebSocket支持）
- [x] Task 0.4: 编写 `backend/requirements.txt` 与 `backend/.env.example`，初始化 `backend/app/main.py` 骨架
- [x] Task 0.5: 编写 `frontend/package.json`、`frontend/vite.config.ts`、`frontend/tsconfig.json`（strict模式）、`.env.development`/`.env.production`
- [x] Task 0.6: 编写 `docs/API_CONTRACT.md`（统一响应体、错误码、分页、时间格式规范）作为前后端契约文档

## 阶段1：核心后端

- [x] Task 1.1: 实现 `backend/app/core/config.py`（pydantic-settings，读取环境变量）
- [x] Task 1.2: 实现 `backend/app/core/database.py`（SQLAlchemy 异步引擎 + Session 工厂）与 `backend/app/core/logging.py`（structlog JSON 日志 + trace_id 中间件） [可并行]
- [x] Task 1.3: 实现 `backend/app/core/exceptions.py`（自定义异常类 + 错误码枚举）与 `backend/app/core/response.py`（统一响应封装函数） [可并行]
- [x] Task 1.4: 实现 `backend/app/core/security.py`（JWT 签发/验证）与 `backend/app/api/deps.py`（get_current_user、get_db、限流依赖） [可并行]
- [x] Task 1.5: 实现 ORM 模型 `backend/app/models/`（Document、Task、Schema、Term、User）
- [x] Task 1.6: 实现 Pydantic Schemas `backend/app/schemas/`（对应每个模型的 Create/Update/Response）
- [x] Task 1.7: 配置 Alembic 迁移（`alembic.ini` + `alembic/env.py`），生成初始迁移脚本
- [x] Task 1.8: 实现 `backend/app/services/storage_service.py`（MinIO 封装：上传、下载、删除）
- [x] Task 1.9: 实现文件管理端点 `backend/app/api/v1/endpoints/documents.py`（上传、列表、删除、详情）
- [x] Task 1.10: 实现鉴权端点 `backend/app/api/v1/endpoints/auth.py`（登录、刷新token）与 `backend/app/api/v1/router.py` 聚合路由
- [x] Task 1.11: 配置 Celery `backend/app/tasks/celery_app.py`（含 beat 定时任务）与 `backend/app/tasks/document_tasks.py` 骨架
- [x] Task 1.12: 实现任务进度 SSE 端点 `backend/app/api/v1/endpoints/tasks.py`（任务提交、状态查询、SSE流）
- [x] Task 1.13: 编写后端单元测试 `backend/tests/`（config、security、documents、auth）覆盖阶段1功能

## 阶段2：文档解析管道

- [ ] Task 2.1: 实现 `backend/app/services/ocr_service.py`（PaddleOCR-VL 封装：recognize、warmup）
- [ ] Task 2.2: 实现 `backend/app/services/layout_service.py`（MinerU 封装：复杂文档版面分析）[可并行]
- [ ] Task 2.3: 实现 `backend/app/services/extract_service.py`（基于 Qwen3.6 的结构化抽取，按Schema输出JSON）
- [ ] Task 2.4: 实现 `backend/app/tasks/document_tasks.py` 的 `parse_document` 任务（编排 OCR→版面→抽取，带进度推送）
- [ ] Task 2.5: 实现 Schema 管理端点 `backend/app/api/v1/endpoints/schemas.py`（CRUD + 模板）
- [ ] Task 2.6: 实现术语标准化服务 `backend/app/services/term_service.py`（术语库匹配 + 人工审核队列）
- [ ] Task 2.7: 实现术语管理端点 `backend/app/api/v1/endpoints/terms.py` [可并行]
- [ ] Task 2.8: 编写解析管道集成测试（使用 `test_standard_doc/` 样本，验证端到端解析流程）

## 阶段3：RAG知识库

- [ ] Task 3.1: 实现 `backend/app/services/chunking_service.py`（结构感知分块器：章节提取 + 递归分块）
- [ ] Task 3.2: 实现 `backend/app/services/embedding_service.py`（bge-base-zh-v1.5 密集 + 稀疏嵌入，batch_size控制）
- [ ] Task 3.3: 编写 Milvus Collection 初始化脚本 `scripts/create_milvus_collection.py`（dense + sparse 字段、IVF_PQ索引）
- [ ] Task 3.4: 实现 `backend/app/services/vector_store.py`（Milvus 封装：插入、混合检索、RRF融合）
- [ ] Task 3.5: 实现 `backend/app/tasks/rag_tasks.py`（文档入知识库任务：分块→嵌入→入库）
- [ ] Task 3.6: 实现知识库管理端点 `backend/app/api/v1/endpoints/knowledge_base.py`（重建索引、状态查询）
- [ ] Task 3.7: 编写RAG知识库单元测试（分块正确性、嵌入维度、检索召回）

## 阶段4：知识图谱

- [ ] Task 4.1: 实现 `backend/app/services/graph_extract_service.py`（基于 LLM 的实体关系抽取）
- [ ] Task 4.2: 实现 `backend/app/services/graph_store.py`（Neo4j 封装：节点/边CRUD、子图查询）
- [ ] Task 4.3: 实现 `backend/app/tasks/graph_tasks.py`（图构建任务：抽取→去重→入库）
- [ ] Task 4.4: 实现知识图谱管理端点 `backend/app/api/v1/endpoints/knowledge_graph.py`（图查询、节点详情）
- [ ] Task 4.5: 编写知识图谱集成测试（实体抽取准确率、关系正确性）

## 阶段5：RAG问答引擎

- [ ] Task 5.1: 实现 `backend/app/services/query_service.py`（查询理解：意图识别 + 实体提取）
- [ ] Task 5.2: 实现 `backend/app/services/reranker_service.py`（bge-reranker-v2-m3 精排封装）[可并行]
- [ ] Task 5.3: 实现 `backend/app/services/rag_service.py`（编排：查询→混合检索→重排→LLM生成→溯源）
- [ ] Task 5.4: 实现问答端点 `backend/app/api/v1/endpoints/qa.py`（普通查询 + SSE流式查询）
- [ ] Task 5.5: 编写RAG问答集成测试（召回率、答案质量、溯源准确性）

## 阶段6：前端实现

- [ ] Task 6.1: 初始化 Vue 项目脚手架（main.ts、App.vue、router、layouts/DefaultLayout.vue、Pinia）
- [ ] Task 6.2: 实现 `frontend/src/api/index.ts`（axios实例 + 拦截器 + trace_id）与 `frontend/src/api/types.ts` 生成脚本（openapi-typescript）
- [ ] Task 6.3: 实现各资源 API 模块 `frontend/src/api/`（document、task、schema、term、knowledge、qa）
- [ ] Task 6.4: 实现 Dashboard 页面 `frontend/src/views/Dashboard/`（统计概览） [可并行]
- [ ] Task 6.5: 实现 Documents 页面 `frontend/src/views/Documents/`（上传区 + 文件列表 + 分页） [可并行]
- [ ] Task 6.6: 实现 Parser 页面 `frontend/src/views/Parser/`（双栏：PdfViewer + BoundingBoxes + ResultPanel）
- [ ] Task 6.7: 实现 Schemas 页面 `frontend/src/views/Schemas/`（SchemaBuilder 动态表单） [可并行]
- [ ] Task 6.8: 实现 Terms 页面 `frontend/src/views/Terms/`（TermList + MatchDialog） [可并行]
- [ ] Task 6.9: 实现 Knowledge 页面 `frontend/src/views/Knowledge/`（GraphViewer Cytoscape） [可并行]
- [ ] Task 6.10: 实现 QA 页面 `frontend/src/views/QA/`（ChatWindow + SourceCard + SSE流式接收）
- [ ] Task 6.11: 编写前端 Dockerfile（多阶段构建）与 nginx.conf 静态托管配置

## 阶段7：集成测试与部署优化

- [ ] Task 7.1: 编写 `deploy/docker-compose.yml` 完整版（含所有服务 + GPU配置 + 显存限制）
- [ ] Task 7.2: 编写 `backend/Dockerfile` 与 `frontend/Dockerfile`（多阶段构建）
- [ ] Task 7.3: 编写端到端测试脚本 `scripts/e2e_test.py`（上传→解析→问答全流程）
- [ ] Task 7.4: 配置 Prometheus + Grafana 监控（`deploy/prometheus.yml` + dashboards）
- [ ] Task 7.5: 编写部署文档 `docs/DEPLOYMENT.md`（一键部署步骤、服务地址、故障排查）
- [ ] Task 7.6: 性能压测与优化（显存使用、并发调优、检索延迟）

---

# Task Dependencies

- Task 0.* 依赖：无（基础设施先行）
- 阶段1 全部 Task 依赖 Task 0.4（backend骨架）
- Task 1.7（Alembic）依赖 Task 1.5（models）
- Task 1.9（documents端点）依赖 Task 1.5、1.6、1.8
- 阶段2 全部 Task 依赖阶段1完成（特别是 Task 1.11 Celery）
- 阶段3 依赖阶段2（解析结果作为分块输入）
- 阶段4 可与阶段3部分并行（Task 4.1-4.2 独立于 RAG）
- 阶段5 依赖阶段3（向量库）+ 阶段4（可选GraphRAG）
- 阶段6 依赖阶段1-5 的API就绪（前端需对接全部API）
  - Task 6.1-6.3 可在阶段1完成后先行
- 阶段7 依赖全部前序阶段完成
