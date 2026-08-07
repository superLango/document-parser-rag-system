# HansonDOC RAG — 领域文档智能解析与检索增强生成系统

**HansonDOC RAG** 是一套以**知识库为隔离边界**的垂直领域文档智能产品，将**结构化抽取**与 **RAG 问答**融为一体。面向航空航天材料检测标准等技术文档领域，提供从文档上传、OCR 识别、版面重建、五维向量索引、配置驱动结构化抽取到知识图谱构建、混合检索、智能问答的全链路能力。系统采用裸机 + GPU 直跑的高性能部署模式，全组件内网运行，数据不出网。

> **品牌含义**：HansonDOC RAG = Hanson + DOC（文档）+ RAG（检索增强生成）

---

## 目录

- [功能特性](#功能特性)
- [系统架构](#系统架构)
- [技术栈](#技术栈)
- [项目结构](#项目结构)
- [快速开始](#快速开始)
- [默认管理员](#默认管理员)
- [文档索引](#文档索引)
- [代码规范](#代码规范)
- [许可证](#许可证)

---

## 功能特性

### 文档解析

- **GLM-OCR 混合模式**：方向校正 + 倾斜校正 + 条件增强 + PP-DocLayoutV3 版面分析 + 区域级 GLM-OCR 识别，整页 Markdown 输出，表格/脚注/阅读顺序最优
- **MinerU-Popo 后处理增强**：跨页表格合并、标题层级重建、图文关联，重建出带结构树的 Markdown
- **多引擎可切换**：GLM-OCR（主）/ MinerU（备）/ PaddleOCR（备），通过配置切换

### 结构化抽取

- **配置驱动**：Schema 模板 + Prompt 模板 + 术语集 + LLM 端点全部可配置，无硬编码回退
- **五维向量检索底座**：path / title / content / type / structural 五维向量，按权重 RRF 融合
- **双轨抽取引擎**：LangExtract（output_schema 强约束 + 类别内并发，质量优先）与 BaseExtract（短/长文本分流 + 分批串行，稳定性优先），可切换并支持降级
- **混合检索**：稠密五维 + 稀疏 BM25 词法路，RRF 融合，词法命中为空的类别直接跳过 LLM 调用
- **类别智能过滤**：gliclass 零样本分类过滤跨类混入分块，减少无效算力
- **术语标准化**：术语集（替代旧数据集概念）匹配 + 精简去重 + 人工审核

### RAG 问答

- **混合检索 + 重排**：稠密五维检索 + BM25 稀疏检索 + bge-reranker-v2-m3 精排（可配置开关）
- **溯源引用**：LLM 生成带来源引用的答案，支持 SSE 流式输出
- **问答历史**：按 KB 隔离的会话历史管理

### 知识图谱

- **NebulaGraph 存储**：替代 Neo4j，原生多 graph space 物理隔离，无需 Enterprise 授权
- **每 KB 独占 graph space**：物理隔离、独立销毁
- **实体关系抽取**：基于 LLM 的实体关系抽取 + 子图查询与可视化
- **优雅降级**：NebulaGraph 不可用时返回空数据而非抛 500

### 平台能力

- **六层知识库隔离**：PostgreSQL RLS + Milvus 分 Collection + MinIO 分 bucket + Nebula 分 space + Redis key 前缀 + 三层配置覆盖
- **RBAC 权限**：用户-知识库多对多 + 4 角色（owner/admin/editor/viewer）+ 超管，显式成员制
- **异步任务队列**：arq + Redis，后台任务 + 轮询模式，任务状态独立追踪
- **一体化公开接口**：免鉴权端到端文档处理通道，外部系统上传 PDF 即可获取抽取结果
- **嵌入预览页面**：左右分栏布局，左侧源 PDF 内联预览，右侧抽取结果
- **可观测性**：Prometheus 指标 + structlog 结构化日志 + 链路追踪 ID

---

## 系统架构

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

> 详细架构设计见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

---

## 技术栈

### 后端

| 技术 | 版本 | 用途 |
|------|------|------|
| FastAPI | 0.115+ | 异步 Web 框架 |
| Pydantic | 2.5+ / pydantic-settings | 数据验证与配置 |
| SQLAlchemy | 2.0+ (asyncpg) | 异步 ORM |
| arq | 0.26+ | 异步任务队列（基于 Redis） |
| Alembic | 1.13+ | 数据库迁移 |
| structlog | 24.1+ | 结构化日志 |
| pymilvus | 2.4+ | 向量数据库客户端 |
| FlagEmbedding | 1.2+ | bge-m3 五维嵌入 |
| langextract | 1.6+ | 结构化信息抽取 |
| mineru | 3.4.3 | 版面分析 |
| boto3 | 1.34+ | MinIO S3 兼容存储客户端 |
| nebula-python | - | NebulaGraph 驱动 |
| slowapi | 0.1.9+ | 接口限流 |
| llama-index-core | 0.11+ | 索引/检索抽象层 |

### 前端

| 技术 | 版本 | 用途 |
|------|------|------|
| Vue | 3.5+ | 组合式 API（`<script setup>`） |
| TypeScript | 5.6+ | 严格模式 |
| Vite | 5.4+ | 构建工具（开发端口 5174） |
| reka-ui | 2.10+ | 无样式可访问组件库（替代 Element Plus） |
| Tailwind CSS | 4.0+ | 原子化样式 |
| Pinia | 2.2+ | 状态管理 |
| vue-router | 4.4+ | 路由 |
| axios | 1.7+ | HTTP 客户端 |
| cytoscape | 3.30+ | 知识图谱可视化 |
| markdown-it | 14.1+ | Markdown 渲染 |
| pdfjs-dist | 3.11+ | PDF 预览 |
| chart.js | 4.5+ | 仪表盘图表 |
| pnpm | 10+ | 包管理 |

### 数据与基础设施

| 组件 | 版本 | 用途 | 部署方式 |
|------|------|------|----------|
| PostgreSQL | 16 | 元数据 / 任务 / 配置（RLS 行级安全） | 原生 |
| Redis | - | 缓存（db0）+ arq 任务队列（db1） | 原生 |
| MinIO | - | 对象存储（S3 兼容，按 KB 分 bucket） | 容器/原生 |
| Milvus | 2.4 | 向量数据库（+ etcd，按 KB 分 Collection） | 容器 |
| NebulaGraph | - | 知识图谱（按 KB 分 graph space） | 容器 |

### AI 模型

| 模型 | 用途 | 部署方式 |
|------|------|----------|
| GLM-OCR | 主 OCR 引擎（整页 Markdown 输出） | vLLM 服务（:9977） |
| Qwen3.6-35B-A3B-FP8 | 主 LLM（结构化抽取 / 问答生成） | vLLM 服务（:9988） |
| bge-m3 | 五维文本嵌入（path/title/content/type/structural） | 本地加载 |
| bge-reranker-v2-m3 | CrossEncoder 精排 | 本地加载 |
| gliclass-multilang-mini | 零样本类别分类过滤 | 本地加载 |
| MinerU-Popo | 版面分析后处理增强 | 本地加载 |
| MinerU / PaddleOCR-VL | 备选 OCR 引擎 | 本地加载 |

---

## 项目结构

```
doc_parse_project/
├── backend/                         # 后端服务（FastAPI）
│   ├── app/
│   │   ├── main.py                  # 应用入口（中间件/路由/生命周期）
│   │   ├── core/                    # 配置、数据库、安全、日志、异常、响应、雪花ID
│   │   ├── api/v1/
│   │   │   ├── endpoints/           # 24 个 API 端点模块
│   │   │   └── router.py            # 路由聚合
│   │   ├── models/                  # SQLAlchemy ORM 模型
│   │   ├── schemas/                 # Pydantic 请求/响应模型
│   │   ├── services/                # 业务逻辑层
│   │   │   ├── ocr/                 # OCR 服务（GLM-OCR/MinerU/PaddleOCR）
│   │   │   ├── popo/                # MinerU-Popo 后处理引擎
│   │   │   ├── vector/              # 五维向量、BM25、分块、重建
│   │   │   ├── extraction/          # 抽取管线与检索
│   │   │   ├── extraction_config/   # 抽取配置（默认值/校验/解析/快照）
│   │   │   ├── graph/               # NebulaGraph 图谱存储
│   │   │   ├── rag/                 # RAG 问答引擎
│   │   │   ├── llm/                 # vLLM 大模型封装
│   │   │   ├── embedding/           # 嵌入服务
│   │   │   ├── term/                # 术语集服务
│   │   │   ├── kb/                  # 知识库生命周期/配置/模板/备份
│   │   │   └── infra/               # 存储/缓存/通知/导出/仪表盘
│   │   ├── tasks/                   # arq 异步任务
│   │   ├── middleware/              # API 版本/IP 白名单中间件
│   │   ├── domain_templates/        # 4 个内置领域模板
│   │   ├── kb_hooks/                # Hook 机制（标准接口）
│   │   └── utils/
│   ├── alembic/versions/            # 数据库迁移
│   ├── data/                        # 运行时数据（BM25模型/OCR输出，gitignore）
│   ├── logs/                        # 运行时日志（gitignore）
│   ├── .env.example                 # 环境变量模板
│   ├── requirements.txt
│   ├── Dockerfile
│   └── start_worker.sh              # arq worker 启动脚本（含 CUDA 环境）
│
├── frontend/                        # 前端服务（Vue 3 + TypeScript）
│   ├── src/
│   │   ├── api/                     # API 封装（含 public 公开接口模块）
│   │   ├── views/                   # 页面（Kb/Settings/admin/embed/error）
│   │   ├── components/              # 通用组件（reka-ui 二次封装）
│   │   ├── stores/                  # Pinia 状态管理
│   │   ├── router/                  # 路由（含 /embed/ 嵌入预览）
│   │   ├── layouts/                 # 布局
│   │   ├── styles/                  # 全局样式
│   │   └── composables/             # 组合式函数
│   ├── package.json
│   └── Dockerfile
│
├── deploy/                          # 部署配置
│   ├── milvus_config/               # Milvus 配置
│   └── seaweedfs_s3.json            # S3 兼容存储配置
│
├── docs/                            # 项目文档
│   ├── ARCHITECTURE.md              # 系统架构
│   ├── API_CONTRACT.md              # 接口契约
│   ├── DEPLOYMENT.md                # 部署指南（资源+模型+应用）
│   └── CONFIGURATION.md             # 配置与运维
│
├── scripts/
│   └── download_model.py            # 模型下载脚本（HF 镜像 + ModelScope 回退）
│
├── models/                          # AI 模型文件（gitignore 排除）
└── README.md
```

---

## 快速开始

### 环境要求

- **GPU**：NVIDIA GPU（建议 120G 显存，最低 40G），CUDA 12.x
- **Python**：3.12+（后端）
- **Node.js**：20+ & pnpm 10+（前端）
- **基础设施**：PostgreSQL 16 / Redis / MinIO / Milvus 2.4 + etcd / NebulaGraph

> 本系统采用**裸机 + GPU 直跑**部署模式（AI 模型与 GPU 服务直接在宿主机运行以充分利用显存），基础设施服务可原生或容器化运行。完整部署流程见 [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)。

### 1. 克隆仓库

```bash
git clone <repo-url>
cd doc_parse_project
```

### 2. 启动基础设施服务

详见 [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md#一资源部署基础设施)。核心服务端口：

| 服务 | 端口 |
|------|------|
| PostgreSQL | 5432 |
| Redis | 6379 |
| MinIO | 9000 |
| Milvus | 19530 |
| NebulaGraph graphd | 9669 |

### 3. 下载 AI 模型

```bash
python scripts/download_model.py
# 使用 HF 镜像（hf-mirror.com）下载，ModelScope 作为回退
# 下载至 models/ 目录：bge-m3、bge-reranker-v2-m3、glm-ocr、gliclass 等
```

### 4. 启动 vLLM 推理服务

```bash
# GLM-OCR 服务（端口 9977）
vllm serve models/glm-ocr --served-model-name glm-ocr --port 9977 ...

# 主 LLM 服务（端口 9988，Qwen3.6-35B-A3B-FP8）
vllm serve models/Qwen/... --served-model-name Qwem3.6-35B-A3B-FP8 --port 9988 ...
```

> 详细参数见 [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md#二模型部署ai模型--vllm服务)。

### 5. 配置后端环境变量

```bash
cp backend/.env.example backend/.env
# 编辑 backend/.env，填入数据库密码、Redis、MinIO、Nebula、vLLM 端点等
```

### 6. 启动后端 API

```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
alembic upgrade head          # 应用数据库迁移
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

API 文档：http://localhost:8000/docs

### 7. 启动 arq 异步 worker

```bash
cd backend
./start_worker.sh             # 已配置 CUDA 环境变量
```

### 8. 启动前端

```bash
cd frontend
pnpm install
pnpm dev
```

前端访问：http://localhost:5174

---

## 默认管理员

| 字段 | 值 |
|------|-----|
| 用户名 | admin |
| 密码 | admin123 |

> **安全提示**：首次登录后请立即修改默认密码。

---

## 文档索引

| 文档 | 内容 |
|------|------|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 系统架构、六层隔离、数据流、核心模块设计 |
| [docs/API_CONTRACT.md](docs/API_CONTRACT.md) | 统一响应体、错误码、鉴权、限流、完整接口目录 |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | 资源部署、模型部署、应用部署、故障排查 |
| [docs/CONFIGURATION.md](docs/CONFIGURATION.md) | 环境变量、抽取配置、领域模板、Hook 机制、运维 |

---

## 代码规范

- **后端**：FastAPI 分层架构（endpoints → services → models），snake_case 命名，Pydantic Schema 以 Create/Update/Response 后缀区分；所有确认/提示框使用自定义 reka-ui Dialog（禁用浏览器原生对话框）
- **前端**：Vue 3 `<script setup lang="ts">`，PascalCase 组件名，reka-ui + Tailwind CSS 4，组合式函数 useXxx
- **API 契约**：统一响应体 `{code, message, data, trace_id}`，分段错误码，ISO 8601 UTC 时间格式
- **配置原则**：消除所有硬编码，提交任务前全量显式配置校验，无静默回退

---

## 许可证

私有项目，未授权不得使用。
