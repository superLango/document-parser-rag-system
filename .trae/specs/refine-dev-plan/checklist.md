# Checklist — 开发方案细化与代码规范验证

## 项目结构与配置
- [x] 顶层目录结构包含 `frontend/`、`backend/`、`deploy/`、`docs/`、`scripts/`
- [x] `.gitignore` 排除 `venv/`、`volumes/`、`models/`、`node_modules/`、`.env`
- [x] `backend/requirements.txt` 包含全部锁定版本的依赖
- [x] `backend/.env.example` 存在且不含敏感值
- [x] `frontend/package.json` 包含全部锁定版本的依赖
- [x] `frontend/tsconfig.json` 启用 strict 模式
- [x] `frontend/.env.development` 与 `.env.production` 存在
- [x] `docs/API_CONTRACT.md` 定义统一响应体、错误码、分页、时间格式

## Docker与部署
- [x] `deploy/docker-compose.yml` 包含 PostgreSQL、Redis、MinIO、Neo4j、Milvus(+etcd)
- [x] `deploy/docker-compose.override.yml` 区分开发环境
- [x] `deploy/nginx.conf` 配置前端静态资源 + API代理 + SSE/WebSocket
- [x] `deploy/redis.conf` 配置 maxmemory 与持久化
- [x] `scripts/init_db.sql` 包含 uuid-ossp、pg_trgm 扩展
- [ ] `scripts/create_milvus_collection.py` 创建 dense+sparse Collection

## 后端代码规范
- [x] 后端目录结构符合 spec（app/core、api/v1/endpoints、models、schemas、services、tasks）
- [x] 文件名使用 snake_case，类名使用 PascalCase
- [x] Pydantic Schema 类以 Create/Update/Response/Base 后缀区分
- [x] `endpoints/` 不含业务逻辑，只调用 service
- [x] `services/` 封装业务逻辑
- [x] `app/core/exceptions.py` 定义自定义异常与错误码
- [x] 全局异常处理器将异常转换为统一响应体
- [x] `app/core/logging.py` 输出 JSON 格式结构化日志
- [x] 请求中间件生成/透传 `X-Trace-Id`
- [x] Celery 配置 `worker_prefetch_multiplier=1`、`task_time_limit=3600`
- [x] Alembic 迁移配置完成且有初始迁移脚本

## 前端代码规范
- [ ] 前端目录结构符合 spec（api、components、layouts、views、stores、router、composables、utils、styles）
- [ ] 组件文件使用 PascalCase.vue
- [ ] 非组件文件使用 camelCase.ts
- [ ] 组合式函数以 use 前缀开头
- [ ] Pinia store 以 use 开头 + Store 后缀
- [ ] 所有组件使用 `<script setup lang="ts">`
- [ ] Props/Emits 使用泛型形式 defineProps<T>()/defineEmits<T>()
- [ ] axios 实例配置请求拦截器（token）与响应拦截器（错误处理）
- [ ] `npm run gen:api` 脚本可从后端 OpenAPI 生成前端类型

## API契约一致性
- [x] 所有成功响应返回 `{code, message, data, trace_id}` 结构
- [x] 所有错误响应返回分段错误码（1xxxx/2xxxx/3xxxx/5xxxx）
- [x] 列表接口返回 `{items, total, page, page_size}` 分页结构
- [x] 时间字段使用 ISO 8601 UTC 格式
- [ ] 前端使用生成的类型，无手写重复类型

## 核心功能实现
- [x] 文件上传接口验证类型与大小，上传至 MinIO
- [x] 文档解析任务通过 Celery 异步执行，支持进度推送
- [x] SSE 端点可流式推送任务进度
- [x] OCR 服务封装 PaddleOCR-VL，含 warmup
- [x] 结构化抽取按 Schema 输出 JSON
- [ ] 分块器支持章节结构感知
- [ ] 嵌入服务控制 batch_size 防止 OOM
- [ ] Milvus 混合检索（Dense+Sparse+RRF）
- [ ] Reranker 精排封装
- [ ] RAG 问答含溯源引用
- [ ] 知识图谱支持节点/边CRUD与子图查询

## 前端页面
- [ ] Dashboard 统计概览页
- [ ] Documents 上传 + 文件列表 + 分页
- [ ] Parser 双栏 PDF预览 + 识别框 + 结果面板
- [ ] Schemas 动态表单构建器
- [ ] Terms 术语列表 + 人工审核弹窗
- [ ] Knowledge Cytoscape 图谱可视化
- [ ] QA 对话窗口 + 溯源卡片 + SSE流式

## 测试
- [ ] 后端单元测试覆盖 config、security、documents、auth
- [ ] 解析管道集成测试使用 test_standard_doc 样本
- [ ] RAG 知识库测试验证分块与检索
- [ ] 知识图谱测试验证实体关系抽取
- [ ] RAG 问答测试验证召回与溯源
- [ ] 端到端测试脚本覆盖上传→解析→问答全流程

## 监控与运维
- [ ] Prometheus 采集 FastAPI 与 arq 指标
- [ ] Grafana dashboard 配置完成
- [ ] arq 任务状态查询API（替代Flower）
- [ ] 显存分配符合规划（MinerU 40-50GB、PaddleOCR 8-10GB 等）
- [ ] 部署文档包含一键部署步骤与服务地址表

## 技术栈迭代迁移（阶段8）
- [x] docker-compose.yml 使用 Valkey 8 替代 Redis（valkey/valkey:8-alpine）
- [x] docker-compose.yml 使用 SeaweedFS 替代 MinIO（chrislusf/seaweedfs:latest）
- [x] valkey.conf 配置完成（原redis.conf迁移）
- [x] storage_service.py 使用 boto3 S3兼容客户端（支持SeaweedFS）
- [x] backend/app/tasks/arq_worker.py 替代 celery_app.py（WorkerSettings配置）
- [x] document_tasks.py 使用 async def parse_document_impl（非@celery.task）
- [x] rag_tasks.py 使用 async def _impl（非@celery.task）
- [x] graph_tasks.py 使用 async def _impl（非@celery.task）
- [x] API端点任务提交使用 arq.enqueue_job()（非celery.delay()）
- [x] graph_extract_service.py 使用 OneKE指令格式 + vLLM（非DeepKE）
- [x] OneKE指令构建正确（schema驱动 + 实体/关系类型 + IEPile格式）
- [ ] popo_service.py 实现MinerU-Popo后处理（跨页表格合并+标题层级）— 暂缓
- [ ] document_tasks.py 解析管道集成Popo后处理步骤 — 暂缓
- [x] requirements.txt 移除 celery/minio/deepke
- [x] requirements.txt 新增 arq/redis[hiredis]/boto3/langextract
- [x] .env.example 更新为Valkey/SeaweedFS配置项
- [x] deepke-env Conda环境已移除
- [x] 全量测试通过（290个测试，迁移后无功能回退）
- [ ] README.md 技术栈说明已更新
