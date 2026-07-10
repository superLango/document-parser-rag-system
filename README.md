# 文档智能解析与 RAG 增强检索系统

基于 **NVIDIA 120G 显存单卡**的私有化文档智能解析与检索增强生成（RAG）系统，面向航空航天材料检测标准文档领域，提供从文档上传、OCR 识别、版面分析、结构化抽取到知识图谱构建、混合检索、智能问答的全链路能力。所有组件容器化部署，数据不出内网。

---

## 功能特性

- **文档解析**：支持文本层 PDF 与扫描件，PaddleOCR-VL 识别 + 版面分析
- **结构化抽取**：基于 LLM 按 Schema 从非结构化文本提取结构化 JSON
- **术语标准化**：术语库匹配 + 人工审核队列
- **知识图谱**：Neo4j 存储实体与关系，支持子图查询与可视化
- **RAG 混合检索**：Dense + Sparse 向量检索 + RRF 融合 + Reranker 精排
- **智能问答**：LLM 生成带溯源引用的答案，支持 SSE 流式输出
- **异步任务**：Celery 处理长耗时解析任务，SSE 实时推送进度
- **私有化部署**：Docker Compose 一键编排，全组件内网运行

---

## 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                    前端层 (Vue 3 + TypeScript)                │
│   文件管理 │ 解析工作室 │ Schema配置 │ 术语管理 │ 知识图谱 │ 问答 │
└──────────────────────────┬──────────────────────────────────┘
                           │ RESTful API / SSE
┌──────────────────────────▼──────────────────────────────────┐
│              API 网关层 (FastAPI + Nginx)                     │
│          路由 │ 鉴权(JWT) │ 限流 │ 日志 │ 静态资源             │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│            核心业务层 (FastAPI + Pydantic + SQLAlchemy)       │
│   文件管理 → 文档解析 → 结构化抽取 → 术语标准化 → 知识图谱    │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│              异步任务层 (Celery + Redis)                     │
│       长耗时任务解耦 │ 状态追踪 │ 重试 │ 进度推送(SSE)        │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│            RAG 检索与问答引擎层                                │
│  查询理解 → 混合检索 → 重排序 → LLM生成 → 溯源引用           │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│              数据持久层                                       │
│  PostgreSQL │ MinIO │ Neo4j │ Redis │ Milvus                │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│            AI 推理引擎层 (GPU 加速)                          │
│  PaddleOCR-VL │ Qwen3.6-35B │ bge-base-zh-v1.5             │
└─────────────────────────────────────────────────────────────┘
```

---

## 技术栈

### 后端

| 技术 | 版本 | 用途 |
|------|------|------|
| FastAPI | 0.115+ | 异步 Web 框架 |
| Pydantic | 2.5+ | 数据验证 |
| SQLAlchemy | 2.0+ | 异步 ORM (asyncpg) |
| Celery | 5.3+ | 异步任务队列 |
| Alembic | 1.13+ | 数据库迁移 |
| structlog | 24.1+ | 结构化日志 |

### 前端

| 技术 | 版本 | 用途 |
|------|------|------|
| Vue | 3.4+ | 组合式 API |
| TypeScript | 5.0+ | 严格模式 |
| Vite | 5.0+ | 构建工具 |
| Element Plus | 2.6+ | UI 组件库 |
| Pinia | 2.1+ | 状态管理 |
| Cytoscape.js | 3.28+ | 知识图谱可视化 |

### 数据与基础设施

| 组件 | 版本 | 用途 |
|------|------|------|
| PostgreSQL | 15 | 元数据 / 任务 |
| MinIO | latest | 文件存储 |
| Neo4j | 5 | 知识图谱 |
| Redis | 7 | 缓存 / 消息队列 |
| Milvus | 2.4 | 向量数据库 |

### AI 模型

| 模型 | 用途 |
|------|------|
| PaddleOCR-VL | OCR 识别 + 版面分析 |
| Qwen3.6-35B-A3B-FP8 | 主 LLM（结构化抽取 / 问答生成） |
| Qwen3.5-9B | 备用 LLM |
| bge-base-zh-v1.5 | 文本嵌入 |

---

## 项目结构

```
doc_parse_project/
├── backend/                    # 后端 (FastAPI)
│   ├── app/
│   │   ├── main.py             # 应用入口
│   │   ├── core/               # 配置、数据库、安全、日志、异常
│   │   ├── api/v1/endpoints/   # API 端点
│   │   ├── models/             # ORM 模型
│   │   ├── schemas/            # Pydantic 模型
│   │   ├── services/           # 业务逻辑层
│   │   └── tasks/              # Celery 异步任务
│   ├── alembic/                # 数据库迁移
│   ├── tests/                  # 测试
│   ├── requirements.txt
│   └── Dockerfile
│
├── frontend/                   # 前端 (Vue 3 + TS)
│   ├── src/
│   │   ├── api/                # API 接口层
│   │   ├── views/              # 页面组件
│   │   ├── stores/             # Pinia 状态管理
│   │   ├── router/             # 路由
│   │   └── composables/        # 组合式函数
│   ├── package.json
│   └── Dockerfile
│
├── deploy/                     # 部署配置
│   ├── docker-compose.yml      # 服务编排
│   ├── docker-compose.override.yml  # 开发环境覆盖
│   ├── nginx.conf              # Nginx 反向代理
│   └── redis.conf              # Redis 配置
│
├── docs/                       # 文档
│   └── API_CONTRACT.md         # API 契约规范
│
├── scripts/                    # 脚本
│   └── init_db.sql             # 数据库初始化
│
└── 基于NVIDIA 120G显存单卡...md  # 原始部署方案文档
```

---

## 快速开始

### 环境要求

- NVIDIA GPU（建议 120G 显存，最低 40G）
- Docker 24.0+ & Docker Compose v2
- NVIDIA Container Toolkit
- Python 3.12+（本地开发）
- Node.js 20+（前端开发）

### 1. 克隆仓库

```bash
git clone https://github.com/superLango/document-parser-rag-system.git
cd document-parser-rag-system
```

### 2. 配置环境变量

```bash
cp deploy/.env.example deploy/.env
# 编辑 deploy/.env 填入真实密码

cp backend/.env.example backend/.env
# 编辑 backend/.env 填入数据库密码等
```

### 3. 启动基础设施服务

```bash
cd deploy
docker compose up -d
```

### 4. 后端开发

```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

访问 API 文档：http://localhost:8000/docs

### 5. 前端开发

```bash
cd frontend
npm install
npm run dev
```

访问前端：http://localhost:5173

---

## 部署

### Docker Compose 一键部署

```bash
cd deploy
cp .env.example .env && vim .env
docker compose up -d
```

### 服务地址

| 服务 | 地址 | 默认凭证 |
|------|------|----------|
| 前端 | http://localhost | - |
| API 文档 | http://localhost:8000/docs | - |
| MinIO 控制台 | http://localhost:9001 | minioadmin / .env 中配置 |
| Neo4j | http://localhost:7474 | neo4j / .env 中配置 |

---

## API 契约

所有 API 遵循统一响应体规范，详见 [API_CONTRACT.md](docs/API_CONTRACT.md)。

**统一响应体**：
```json
{
  "code": 0,
  "message": "success",
  "data": {},
  "trace_id": "uuid"
}
```

**错误码分段**：
- `1xxxx` — 参数校验错误
- `2xxxx` — 鉴权 / 权限错误
- `3xxxx` — 业务逻辑错误
- `5xxxx` — 系统内部错误

---

## 开发路线图

项目分 8 个阶段递进交付，详见 [tasks.md](.trae/specs/refine-dev-plan/tasks.md)。

| 阶段 | 内容 | 状态 |
|------|------|------|
| 阶段 0 | 项目脚手架与基础设施 | ✅ 完成 |
| 阶段 1 | 核心后端（鉴权、文件管理、Celery、SSE） | 开发中 |
| 阶段 2 | 文档解析管道（OCR → 版面 → 抽取） | 待开始 |
| 阶段 3 | RAG 知识库（分块 → 嵌入 → Milvus） | 待开始 |
| 阶段 4 | 知识图谱（Neo4j） | 待开始 |
| 阶段 5 | RAG 问答引擎 | 待开始 |
| 阶段 6 | 前端实现 | 待开始 |
| 阶段 7 | 集成测试与部署优化 | 待开始 |

---

## 代码规范

- **后端**：FastAPI 分层架构（endpoints → services → models），snake_case 命名，Pydantic Schema 以 Create/Update/Response 后缀区分
- **前端**：Vue 3 `<script setup lang="ts">`，PascalCase 组件名，useXxx 组合式函数，OpenAPI 自动生成类型
- **API 契约**：统一响应体、分段错误码、ISO 8601 UTC 时间格式

---

## 许可证

私有项目，未授权不得使用。
