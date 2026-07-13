# Hansight — 文档智能解析与 RAG 增强检索系统

基于 **NVIDIA 120G 显存单卡**的私有化文档智能解析与检索增强生成（RAG）系统，面向航空航天材料检测标准文档领域，提供从文档上传、OCR 识别、版面分析、结构化抽取到知识图谱构建、混合检索、智能问答的全链路能力。所有组件容器化部署，数据不出内网。

> **品牌含义**：Hansight = Han（Hanson）+ Sight（洞察）= 智能文档洞察

---

## 功能特性

- **文档解析**：PaddleOCR-VL 识别 + MinerU 版面分析 + MinerU-Popo 后处理增强（跨页表格合并、标题层级重建、图文关联）
- **结构化抽取**：LangExtract 按 Schema 从非结构化文本提取结构化 JSON，无需自定义 Prompt + vLLM Python API
- **术语标准化**：术语库匹配 + 人工审核队列
- **知识图谱**：OneKE/DeepKE-LLM 实体关系抽取 + Neo4j 存储，支持子图查询与可视化；Neo4j 不可用时优雅降级
- **RAG 混合检索**：bge-m3 Dense+Sparse 双向量检索 + RRF 融合 + bge-reranker-v2-m3 精排
- **智能问答**：LLM 生成带溯源引用的答案，支持 SSE 流式输出
- **异步任务**：arq + Valkey 异步任务队列（async/await），SSE 实时推送进度
- **私有化部署**：Docker Compose 一键编排，全组件内网运行
- **可观测性**：Prometheus + Grafana 监控，覆盖后端 API、arq Worker、数据库等核心组件

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
│              异步任务层 (arq + Valkey)                        │
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
│  PostgreSQL │ SeaweedFS │ Neo4j │ Valkey │ Milvus           │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│            AI 推理引擎层 (GPU 加速)                          │
│  PaddleOCR-VL │ MinerU+Popo │ Qwen3.5-9B │ bge-m3 │ OneKE  │
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
| arq | 0.26+ | 异步任务队列（async/await） |
| Alembic | 1.13+ | 数据库迁移 |
| structlog | 24.1+ | 结构化日志 |
| LangExtract | 1.6+ | 结构化信息抽取 |
| neo4j | 5.14+ | 知识图谱驱动 |
| pymilvus | 2.4+ | 向量数据库客户端 |
| FlagEmbedding | 1.2+ | bge-m3 嵌入模型 |

### 前端

| 技术 | 版本 | 用途 |
|------|------|------|
| Vue | 3.5+ | 组合式 API |
| TypeScript | 5.6+ | 严格模式 |
| Vite | 5.4+ | 构建工具（端口 5174） |
| Element Plus | 2.8+ | UI 组件库（importStyle: false） |
| Pinia | 2.2+ | 状态管理 |
| Cytoscape.js | 3.30+ | 知识图谱可视化 |
| pnpm | 10+ | 包管理（registry: npmmirror.com） |

### 数据与基础设施

| 组件 | 版本 | 用途 |
|------|------|------|
| PostgreSQL | 15 | 元数据 / 任务 |
| SeaweedFS | latest | 对象存储（S3 兼容） |
| Neo4j | 5 Enterprise | 知识图谱（APOC + GDS 插件） |
| Valkey | 8 | 缓存 / 消息队列（Redis 兼容） |
| Milvus | 2.4 | 向量数据库 |

### AI 模型

| 模型 | 用途 |
|------|------|
| PaddleOCR-VL | OCR 识别 + 版面分析 |
| MinerU + MinerU-Popo | 复杂版面分析 + 后处理增强 |
| Qwen3.5-9B | 主 LLM（结构化抽取 / 问答生成） |
| bge-m3 | 文本嵌入（Dense + Sparse 双向量） |
| bge-reranker-v2-m3 | CrossEncoder 精排 |
| OneKE/DeepKE-LLM | 知识图谱实体关系抽取 |

---

## 项目结构

```
doc_parse_project/
├── backend/                         # 后端服务（FastAPI）
│   ├── app/
│   │   ├── main.py                  # 应用入口，注册路由与中间件
│   │   ├── core/                    # 核心模块：配置、数据库、安全、日志、异常、响应
│   │   ├── api/v1/endpoints/        # API 端点：auth、documents、dashboard、schemas、terms、knowledge_graph、qa 等
│   │   ├── models/                  # SQLAlchemy ORM 模型
│   │   ├── schemas/                 # Pydantic 请求/响应模型
│   │   ├── services/                # 业务逻辑层：OCR、抽取、分块、嵌入、检索、图谱
│   │   ├── tasks/                   # arq 异步任务：文档解析、向量入库、图谱构建
│   │   ├── popo/                    # MinerU-Popo 后处理引擎
│   │   └── utils/                   # 工具函数
│   ├── alembic/                     # 数据库迁移脚本
│   ├── requirements.txt
│   └── Dockerfile
│
├── frontend/                        # 前端服务（Vue 3 + TypeScript）
│   ├── src/
│   │   ├── api/                     # API 接口封装
│   │   ├── components/              # 通用组件（含 BrandLogo）
│   │   ├── views/                   # 页面组件
│   │   ├── stores/                  # Pinia 状态管理
│   │   ├── router/                  # Vue Router 路由
│   │   ├── layouts/                 # 布局组件
│   │   ├── styles/                  # 全局样式与变量
│   │   └── composables/             # 组合式函数
│   ├── package.json
│   └── Dockerfile
│
├── deploy/                          # 部署配置
│   ├── docker-compose.yml           # 生产环境服务编排
│   ├── docker-compose.override.yml  # 开发环境覆盖配置
│   ├── .env.example                 # 环境变量模板
│   ├── nginx.conf                   # Nginx 反向代理配置
│   ├── prometheus.yml               # Prometheus 监控配置
│   ├── valkey.conf                  # Valkey（Redis 兼容）配置
│   ├── seaweedfs_s3.json            # SeaweedFS S3 配置
│   └── grafana/                     # Grafana 仪表盘与数据源配置
│
├── docs/                            # 项目文档
│   ├── API_CONTRACT.md              # API 契约规范
│   └── DEPLOYMENT.md                # 部署指南
│
├── scripts/                         # 运维脚本
│   ├── init_db.sql                  # 数据库初始化 SQL
│   └── create_milvus_collection.py  # Milvus Collection 初始化
│
├── models/                          # AI 模型文件（.gitignore 排除）
│   ├── bge-m3/                      # BGE 嵌入模型
│   ├── bge-reranker-v2-m3/          # BGE 重排模型
│   ├── MinerU-Popo/                 # 版面分析后处理模型
│   └── PaddlePaddle/PaddleOCR-VL/  # OCR 识别模型
│
├── download_model.py               # 模型下载脚本（HF 镜像 + ModelScope 回退）
└── README.md
```

---

## 快速开始

### 环境要求

- NVIDIA GPU（建议 120G 显存，最低 40G）
- Docker 24.0+ & Docker Compose v2
- NVIDIA Container Toolkit
- Python 3.12+（本地开发）
- Node.js 20+ & pnpm 10+（前端开发）

### 1. 克隆仓库

```bash
git clone https://github.com/superLango/document-parser-rag-system.git
cd document-parser-rag-system
```

### 2. 下载 AI 模型

```bash
python download_model.py
# 使用 HF 镜像（hf-mirror.com）下载，ModelScope 作为回退
# 下载至 models/ 目录：bge-m3、bge-reranker-v2-m3、MinerU-Popo
```

### 3. 配置环境变量

```bash
cp deploy/.env.example deploy/.env
# 编辑 deploy/.env 填入真实密码（POSTGRES_PASSWORD、JWT_SECRET_KEY 等）

cp backend/.env.example backend/.env
# 编辑 backend/.env 填入数据库密码、Neo4j 凭证等
```

### 4. 启动基础设施服务

```bash
cd deploy
docker compose up -d
```

### 5. 后端开发

```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

访问 API 文档：http://localhost:8000/docs

### 6. 前端开发

```bash
cd frontend
pnpm install
pnpm dev
```

访问前端：http://localhost:5174

### 7. 默认管理员

| 字段 | 值 |
|------|-----|
| 用户名 | admin |
| 密码 | admin123 |

> **安全提示**：首次登录后请立即修改默认密码。

---

## 部署

### Docker Compose 一键部署

```bash
cd deploy
cp .env.example .env && vim .env
docker compose up -d
```

### 服务地址

| 服务 | 端口 | URL | 默认凭证 |
|------|------|-----|----------|
| 前端 | 80 | http://localhost | - |
| API 文档 | 8000 | http://localhost:8000/docs | - |
| PostgreSQL | 5432 | localhost:5432 | postgres / .env 中配置 |
| Valkey | 6379 | localhost:6379 | - |
| SeaweedFS | 9000 | http://localhost:9000 | .env 中配置 |
| Neo4j | 7474 | http://localhost:7474 | neo4j / .env 中配置 |
| Milvus | 19530 | localhost:19530 | - |
| Prometheus | 9090 | http://localhost:9090 | - |
| Grafana | 3001 | http://localhost:3001 | admin / admin |

> 详细部署流程见 [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)

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

项目分 9 个阶段递进交付，详见 [tasks.md](.trae/specs/refine-dev-plan/tasks.md)。

| 阶段 | 内容 | 状态 |
|------|------|------|
| 阶段 0 | 项目脚手架与基础设施 | ✅ 完成 |
| 阶段 1 | 核心后端（鉴权、文件管理、arq、SSE） | ✅ 完成 |
| 阶段 2 | 文档解析管道（OCR → 版面 → 抽取） | ✅ 完成 |
| 阶段 3 | RAG 知识库（分块 → 嵌入 → Milvus） | ✅ 完成 |
| 阶段 4 | 知识图谱（Neo4j） | ✅ 完成 |
| 阶段 5 | RAG 问答引擎 | ✅ 完成 |
| 阶段 6 | 前端实现 | ✅ 完成 |
| 阶段 7 | 集成测试与部署优化 | ✅ 完成 |
| 阶段 8 | 技术栈迭代迁移（Valkey/arq/OneKE/MinerU-Popo） | ✅ 完成 |
| 阶段 9 | 品牌重塑、Bug 修复与项目清理 | ✅ 完成 |

---

## 代码规范

- **后端**：FastAPI 分层架构（endpoints → services → models），snake_case 命名，Pydantic Schema 以 Create/Update/Response 后缀区分
- **前端**：Vue 3 `<script setup lang="ts">`，PascalCase 组件名，useXxx 组合式函数，Element Plus 组件按需导入（importStyle: false）
- **API 契约**：统一响应体、分段错误码、ISO 8601 UTC 时间格式

---

## 变更记录

### v1.0.0（2026-07-13）

#### 品牌重塑
- 项目名称由 DocParser 更名为 **Hansight**（Han + Sight = 智能文档洞察）
- 设计全新品牌 Logo：眼形轮廓 + 文档结构线条 + 焦点圆点，蓝色渐变
- 更新前端、后端、部署配置、监控配置、部署文档中的品牌名称

#### Bug 修复
- 修复知识图谱页面"服务器内部错误"：Neo4j 不可用时 `graph_store.py` 优雅降级返回空数据，而非抛出 500 异常

#### 技术栈迭代（阶段 8）
- **Redis → Valkey 8**：缓存与消息队列迁移至 Valkey（Redis 兼容）
- **MinIO → SeaweedFS**：对象存储迁移至 SeaweedFS（RustFS 不可用，SeaweedFS 为生产就绪方案）
- **Celery → arq**：异步任务队列迁移至 arq（async/await，替代 Celery 同步模式）
- **DeepKE → OneKE**：知识图谱实体关系抽取迁移至 OneKE/DeepKE-LLM InstructKGC API
- **bge-base-zh-v1.5 → bge-m3**：嵌入模型升级，支持 Dense + Sparse 双向量输出
- **新增 bge-reranker-v2-m3**：CrossEncoder 精排模型
- **新增 MinerU-Popo**：OCR 后处理增强层（跨页表格合并、标题层级重建、图文关联）
- **新增 LangExtract**：结构化抽取替代自定义 Prompt + vLLM Python API

#### 工程优化
- 前端包管理由 npm 迁移至 **pnpm**（registry: npmmirror.com）
- 前端开发端口由 5173 改为 **5174**（避免与 TRAE IDE 端口冲突）
- 前端主题由暗色调整为亮色（#F8FAFC 背景 + #2563EB 主色）
- 左侧导航菜单增加 Element Plus 图标与折叠功能
- 鉴权 API 改为 JSON 载荷，Token 包含 `expires_in` 字段，User.id 为 UUID 字符串类型

#### 清理
- 移除全部测试文件：前端测试（8 个 API 模块测试 + 2 个 Store 测试 + 测试辅助文件 + vitest 配置）、后端测试（24 个 pytest 文件）、脚本测试（e2e/perf/integration）
- 清理测试依赖：移除 vitest、@vitest/coverage-v8、@vue/test-utils、jsdom

---

## 许可证

私有项目，未授权不得使用。
