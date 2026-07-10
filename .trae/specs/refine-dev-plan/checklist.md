# Checklist — 开发方案细化与代码规范验证

## 项目结构与配置
- [ ] 顶层目录结构包含 `frontend/`、`backend/`、`deploy/`、`docs/`、`scripts/`
- [ ] `.gitignore` 排除 `venv/`、`volumes/`、`models/`、`node_modules/`、`.env`
- [ ] `backend/requirements.txt` 包含全部锁定版本的依赖
- [ ] `backend/.env.example` 存在且不含敏感值
- [ ] `frontend/package.json` 包含全部锁定版本的依赖
- [ ] `frontend/tsconfig.json` 启用 strict 模式
- [ ] `frontend/.env.development` 与 `.env.production` 存在
- [ ] `docs/API_CONTRACT.md` 定义统一响应体、错误码、分页、时间格式

## Docker与部署
- [ ] `deploy/docker-compose.yml` 包含 PostgreSQL、Redis、MinIO、Neo4j、Milvus(+etcd)
- [ ] `deploy/docker-compose.override.yml` 区分开发环境
- [ ] `deploy/nginx.conf` 配置前端静态资源 + API代理 + SSE/WebSocket
- [ ] `deploy/redis.conf` 配置 maxmemory 与持久化
- [ ] `scripts/init_db.sql` 包含 uuid-ossp、pg_trgm 扩展
- [ ] `scripts/create_milvus_collection.py` 创建 dense+sparse Collection

## 后端代码规范
- [ ] 后端目录结构符合 spec（app/core、api/v1/endpoints、models、schemas、services、tasks）
- [ ] 文件名使用 snake_case，类名使用 PascalCase
- [ ] Pydantic Schema 类以 Create/Update/Response/Base 后缀区分
- [ ] `endpoints/` 不含业务逻辑，只调用 service
- [ ] `services/` 封装业务逻辑
- [ ] `app/core/exceptions.py` 定义自定义异常与错误码
- [ ] 全局异常处理器将异常转换为统一响应体
- [ ] `app/core/logging.py` 输出 JSON 格式结构化日志
- [ ] 请求中间件生成/透传 `X-Trace-Id`
- [ ] Celery 配置 `worker_prefetch_multiplier=1`、`task_time_limit=3600`
- [ ] Alembic 迁移配置完成且有初始迁移脚本

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
- [ ] 所有成功响应返回 `{code, message, data, trace_id}` 结构
- [ ] 所有错误响应返回分段错误码（1xxxx/2xxxx/3xxxx/5xxxx）
- [ ] 列表接口返回 `{items, total, page, page_size}` 分页结构
- [ ] 时间字段使用 ISO 8601 UTC 格式
- [ ] 前端使用生成的类型，无手写重复类型

## 核心功能实现
- [ ] 文件上传接口验证类型与大小，上传至 MinIO
- [ ] 文档解析任务通过 Celery 异步执行，支持进度推送
- [ ] SSE 端点可流式推送任务进度
- [ ] OCR 服务封装 PaddleOCR-VL，含 warmup
- [ ] 结构化抽取按 Schema 输出 JSON
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
- [ ] Prometheus 采集 FastAPI 与 Celery 指标
- [ ] Grafana dashboard 配置完成
- [ ] Flower 监控 Celery 任务
- [ ] 显存分配符合规划（MinerU 40-50GB、PaddleOCR 8-10GB 等）
- [ ] 部署文档包含一键部署步骤与服务地址表
