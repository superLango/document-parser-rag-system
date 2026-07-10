# 文档智能解析与RAG系统开发方案细化与代码规范统一 Spec

## Why

项目目录下已存在一份《基于NVIDIA 120G显存单卡的文档智能解析与RAG增强检索系统 —— 完整私有化部署方案》，该方案以**部署视角**详述了技术选型、Docker配置与硬件分配，但缺乏**开发视角**的执行落地标准：无统一前后端代码规范、无分阶段开发路线图、无API契约约定、无项目目录约定。本Spec旨在在已有部署方案基础上，细化开发细节，统一代码规范，形成可直接指导编码实施的完整、有层次、清晰的计划。

## What Changes

### 细化方案细节
- 将部署方案中的技术选型固化为**版本锁定清单**（前后端依赖、模型版本）
- 补全部署方案未覆盖的**开发流程规范**（分支策略、提交规范、Code Review）
- 明确**显存调度策略**与任务并发控制的具体实现方案
- 补充部署方案中**错误处理、日志规范、配置管理**的落地细节

### 统一前后端代码规范
- **BREAKING**：确立前后端统一的 API 契约规范（统一响应体、错误码、分页、时间格式）
- **BREAKING**：确立统一命名约定（驼峰/下划线转换边界、文件命名、组件命名）
- 确立前端代码规范（Vue 3 组合式 API、TS 严格模式、目录约定、状态管理规范）
- 确立后端代码规范（FastAPI 分层架构、Pydantic 模型规范、依赖注入、异常处理）
- 确立前后端**类型同步机制**（OpenAPI 自动生成前端类型）

### 形成完整计划
- 建立分阶段开发路线图（8个阶段，从脚手架到部署）
- 明确每阶段交付物与验收标准
- 明确任务依赖关系与并行化策略

## Impact
- Affected specs: 全系统（前端、后端、AI推理、RAG、数据层、部署）
- Affected code: 新建 `frontend/`、`backend/` 全部源码目录结构
- Affected docs: 原部署方案文档作为附录参考，本Spec为开发主纲

---

## ADDED Requirements

### Requirement: 统一项目目录结构

系统 SHALL 采用前后端分离的 monorepo 目录结构，前后端代码位于同一仓库的不同顶层目录。

#### Scenario: 目录结构规范
- **GIVEN** 项目根目录 `/home/hanson/doc_parse_project`
- **WHEN** 开发者克隆仓库
- **THEN** 根目录 SHALL 包含以下顶层目录：
  - `frontend/` — Vue 3 + TypeScript 前端
  - `backend/` — FastAPI 后端
  - `deploy/` — Docker Compose、Nginx、脚本等部署资源
  - `docs/` — 开发文档（API契约、架构图）
  - `scripts/` — 初始化与运维脚本
  - `test_standard_doc/` — 测试样本文档（已存在）
  - `models/` — 模型文件（已存在）
- **AND** `venv/`、`volumes/` 保留为运行时数据，不纳入版本控制

### Requirement: 统一API契约规范

系统 SHALL 遵循统一的 API 响应体与错误处理规范，前后端共享同一套契约定义。

#### Scenario: 统一响应体
- **WHEN** 任意 API 端点返回成功响应
- **THEN** 响应体 SHALL 采用结构：
  ```json
  {"code": 0, "message": "success", "data": {...}, "trace_id": "uuid"}
  ```
- **AND** `code=0` 表示成功，非零表示业务错误
- **AND** `trace_id` 用于全链路日志追踪

#### Scenario: 统一错误码
- **WHEN** API 发生错误
- **THEN** 错误码 SHALL 采用分段设计：
  - `1xxxx` 参数校验错误
  - `2xxxx` 鉴权/权限错误
  - `3xxxx` 业务逻辑错误
  - `5xxxx` 系统内部错误

#### Scenario: 统一分页
- **WHEN** 列表接口返回分页数据
- **THEN** `data` SHALL 采用结构：
  ```json
  {"items": [...], "total": 100, "page": 1, "page_size": 20}
  ```

#### Scenario: 统一时间格式
- **WHEN** API 传输时间字段
- **THEN** 时间 SHALL 采用 ISO 8601 字符串（UTC，带时区），如 `2026-07-10T08:00:00Z`
- **AND** 前端展示时转换为本地时区

### Requirement: 后端代码规范

后端 SHALL 遵循分层架构与命名规范。

#### Scenario: 后端目录结构
- **GIVEN** `backend/` 目录
- **WHEN** 组织后端代码
- **THEN** 目录 SHALL 为：
  ```
  backend/
  ├── app/
  │   ├── main.py              # FastAPI 应用入口
  │   ├── core/                # 核心基础设施
  │   │   ├── config.py        # pydantic-settings 配置
  │   │   ├── database.py      # SQLAlchemy 异步引擎
  │   │   ├── security.py      # JWT 鉴权
  │   │   ├── exceptions.py    # 统一异常定义
  │   │   └── logging.py       # 日志配置
  │   ├── api/
  │   │   ├── deps.py          # 公共依赖（鉴权、DB会话、限流）
  │   │   └── v1/
  │   │       ├── router.py    # 路由聚合
  │   │       └── endpoints/   # 各资源端点
  │   ├── models/              # SQLAlchemy ORM 模型
  │   ├── schemas/             # Pydantic 请求/响应模型
  │   ├── services/            # 业务逻辑层
  │   ├── tasks/               # Celery 异步任务
  │   └── utils/               # 工具函数
  ├── alembic/                 # 数据库迁移
  ├── tests/                   # 测试（镜像 app/ 结构）
  ├── requirements.txt
  └── Dockerfile
  ```

#### Scenario: 命名规范
- **WHEN** 命名后端模块
- **THEN** 文件名 SHALL 使用 `snake_case`
- **AND** 类名 SHALL 使用 `PascalCase`
- **AND** 函数/变量 SHALL 使用 `snake_case`
- **AND** 常量 SHALL 使用 `UPPER_SNAKE_CASE`
- **AND** Pydantic Schema 类 SHALL 以 `Create`/`Update`/`Response`/`Base` 后缀区分用途

#### Scenario: 分层职责
- **WHEN** 实现业务功能
- **THEN** `endpoints/` 只负责参数解析与调用 service，不含业务逻辑
- **AND** `services/` 封装业务逻辑，可调用 models 与外部服务
- **AND** `models/` 只定义数据结构，不含业务逻辑
- **AND** `schemas/` 独立于 models，负责请求/响应验证

#### Scenario: 异常处理
- **WHEN** 业务异常发生
- **THEN** SHALL 抛出 `app/core/exceptions.py` 中定义的自定义异常
- **AND** 全局异常处理器 SHALL 捕获并转换为统一响应体
- **AND** 未捕获异常 SHALL 记录完整堆栈并返回 `5xxxx` 错误码

### Requirement: 前端代码规范

前端 SHALL 遵循组合式 API 与 TypeScript 严格模式。

#### Scenario: 前端目录结构
- **GIVEN** `frontend/` 目录
- **WHEN** 组织前端代码
- **THEN** 目录 SHALL 为：
  ```
  frontend/
  ├── src/
  │   ├── main.ts
  │   ├── App.vue
  │   ├── api/                 # API 接口层（按资源分文件）
  │   │   ├── index.ts         # axios 实例与拦截器
  │   │   └── types.ts         # OpenAPI 自动生成的类型
  │   ├── components/          # 通用组件（跨页面复用）
  │   ├── layouts/             # 布局组件
  │   ├── views/               # 页面（路由级）
  │   ├── stores/              # Pinia 状态管理
  │   ├── router/
  │   ├── composables/         # 组合式函数（useXxx）
  │   ├── utils/
  │   └── styles/
  ├── package.json
  ├── vite.config.ts
  └── tsconfig.json
  ```

#### Scenario: 命名规范
- **WHEN** 命名前端文件与组件
- **THEN** 组件文件 SHALL 使用 `PascalCase.vue`（如 `FileList.vue`）
- **AND** 非组件文件 SHALL 使用 `camelCase.ts`（如 `request.ts`）
- **AND** 组合式函数 SHALL 以 `use` 前缀开头（如 `useTaskProgress`）
- **AND** Pinia store SHALL 以 `use` 开头 + `Store` 后缀（如 `useDocumentStore`）

#### Scenario: 组件规范
- **WHEN** 编写 Vue 组件
- **THEN** SHALL 使用 `<script setup lang="ts">` 语法
- **AND** Props SHALL 使用 `defineProps<T>()` 泛型形式
- **AND** Emits SHALL 使用 `defineEmits<T>()` 泛型形式
- **AND** 禁止使用 Options API

### Requirement: 前后端类型同步

系统 SHALL 通过 OpenAPI 自动生成前端 TypeScript 类型，保持前后端契约一致。

#### Scenario: 类型同步流程
- **WHEN** 后端 API 定义更新
- **THEN** 运行 `npm run gen:api` SHALL 从后端 `/openapi.json` 生成前端类型到 `src/api/types.ts`
- **AND** 前端 API 调用 SHALL 使用生成的类型，禁止手写重复类型

### Requirement: 配置管理规范

系统 SHALL 区分开发、测试、生产环境配置。

#### Scenario: 后端配置
- **WHEN** 管理后端配置
- **THEN** SHALL 使用 `pydantic-settings` 从 `.env` 读取
- **AND** SHALL 提供 `.env.example` 作为模板（不含敏感值）
- **AND** 敏感配置（密码、密钥）SHALL 仅通过环境变量注入，禁止硬编码

#### Scenario: 前端配置
- **WHEN** 管理前端配置
- **THEN** SHALL 使用 Vite 环境变量（`VITE_` 前缀）
- **AND** SHALL 提供 `.env.development` 与 `.env.production`

### Requirement: 日志与可观测性规范

系统 SHALL 采用结构化日志与统一 trace_id。

#### Scenario: 后端日志
- **WHEN** 后端记录日志
- **THEN** SHALL 使用 `structlog` 或标准 `logging` 输出 JSON 格式
- **AND** 每条日志 SHALL 包含 `trace_id`、`timestamp`、`level`、`module`、`message`
- **AND** 请求入口 SHALL 生成或透传 `trace_id`（`X-Trace-Id` 头）

#### Scenario: 前端日志
- **WHEN** 前端需记录错误
- **THEN** SHALL 通过 API 上报至后端 `/api/v1/logs` 端点
- **AND** SHALL 携带当前 `trace_id`

### Requirement: 显存调度与并发控制

系统 SHALL 实现显存资源池化调度，防止单卡 OOM。

#### Scenario: 显存分配
- **GIVEN** 单卡 120GB 显存
- **WHEN** 各模型服务加载
- **THEN** 显存分配 SHALL 遵循：
  - MinerU: 40-50GB（4-6路并发）
  - PaddleOCR: 8-10GB
  - Ollama (gemma2:2b): 4-6GB
  - bge-m3 dense + sparse: 6GB
  - bge-reranker-v2-m3: 3.5GB
  - 预留缓冲: 40GB+

#### Scenario: Celery 并发控制
- **WHEN** 启动 Celery Worker
- **THEN** SHALL 设置 `worker_prefetch_multiplier=1` 防止任务堆积
- **AND** SHALL 通过信号量（`multiprocessing.Semaphore`）限制 GPU 任务并发数
- **AND** SHALL 设置 `task_time_limit=3600`、`task_soft_time_limit=3000`

### Requirement: 分阶段开发路线图

系统开发 SHALL 分8个阶段递进交付，每阶段有明确验收标准。

#### Scenario: 阶段划分
- **WHEN** 规划开发进度
- **THEN** 阶段 SHALL 为：
  1. 阶段0：项目脚手架与基础设施（目录、Docker、CI、配置）
  2. 阶段1：核心后端（数据模型、鉴权、文件管理、基础API）
  3. 阶段2：文档解析管道（OCR、版面分析、结构化抽取）
  4. 阶段3：RAG知识库（分块、嵌入、Milvus、索引）
  5. 阶段4：知识图谱（Neo4j、实体关系抽取、图构建）
  6. 阶段5：RAG问答引擎（混合检索、重排、LLM生成、溯源）
  7. 阶段6：前端实现（各页面、SSE、图谱可视化）
  8. 阶段7：集成测试与部署优化

## MODIFIED Requirements

### Requirement: 部署方案细化
原部署方案中的技术选型保留，但 SHALL 补充以下开发约束：
- 所有 Python 服务 SHALL 运行于 `backend/` 目录下的统一虚拟环境
- 所有 Docker 镜像 SHALL 使用多阶段构建，基础镜像固定为 `python:3.12-slim` 与 `node:20-alpine`
- 所有服务 SHALL 通过 `docker-compose.yml` 编排，开发环境与生产环境使用不同的 override 文件

---

## 技术选型锁定清单

### 后端依赖（`backend/requirements.txt`）
| 包 | 版本 | 用途 |
|---|---|---|
| fastapi | 0.115+ | Web框架 |
| uvicorn[standard] | 0.30+ | ASGI服务器 |
| pydantic | 2.5+ | 数据验证 |
| pydantic-settings | 2.1+ | 配置管理 |
| sqlalchemy[asyncio] | 2.0+ | ORM |
| asyncpg | 0.29+ | PG异步驱动 |
| alembic | 1.13+ | 数据库迁移 |
| celery | 5.3+ | 异步任务 |
| redis | 5.0+ | 缓存/队列 |
| python-jose[cryptography] | 3.3+ | JWT |
| slowapi | 0.1.9+ | 限流 |
| minio | 7.2+ | 对象存储客户端 |
| pymilvus | 2.4+ | 向量数据库客户端 |
| neo4j | 5.14+ | 图数据库客户端 |
| ollama | 0.3+ | 本地LLM客户端 |
| sentence-transformers | 3.0+ | 嵌入模型 |
| structlog | 24.1+ | 结构化日志 |

### 前端依赖（`frontend/package.json`）
| 包 | 版本 | 用途 |
|---|---|---|
| vue | 3.4+ | 框架 |
| typescript | 5.0+ | 类型 |
| vite | 5.0+ | 构建 |
| element-plus | 2.6+ | UI库 |
| pinia | 2.1+ | 状态管理 |
| vue-router | 4.2+ | 路由 |
| axios | 1.6+ | HTTP |
| @vueuse/core | 10.0+ | 组合式工具 |
| pdfjs-dist | 3.11+ | PDF渲染 |
| cytoscape | 3.28+ | 图谱可视化 |
| marked | 11.0+ | Markdown渲染 |
| highlight.js | 11.9+ | 代码高亮 |

### 模型版本（已存在）
| 模型 | 路径 | 用途 |
|---|---|---|
| Qwen3.6-35B-A3B-FP8 | `models/Qwen/Qwen3.6-35B-A3B-FP8` | 主LLM |
| Qwen3.5-9B | `models/Qwen/Qwen3.5-9B` | 备用LLM |
| PaddleOCR-VL | `models/PaddlePaddle/PaddleOCR-VL` | OCR |
| bge-base-zh-v1.5 | `models/bge-base-zh-v1.5` | 嵌入 |
