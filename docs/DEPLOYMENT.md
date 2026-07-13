# Hansight 部署指南

本文档描述 Hansight（文档智能解析与 RAG 增强检索系统）的私有化部署流程，涵盖一键部署、服务地址、故障排查与开发环境配置。

---

## 一、一键部署步骤

### 1.1 环境前提

| 依赖 | 最低版本 | 说明 |
|------|----------|------|
| Docker | 24.0+ | 容器运行时 |
| Docker Compose | v2 | 服务编排（随 Docker 一并安装） |
| NVIDIA Driver | 535+ | GPU 驱动，需支持 CUDA 12.x |
| nvidia-container-toolkit | 最新 | 使容器内可访问宿主机 GPU |

验证 GPU 可用性：

```bash
# 确认宿主机 GPU 驱动正常
nvidia-smi

# 确认 nvidia-container-toolkit 已安装并配置
nvidia-ctk --version
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker

# 验证容器内可访问 GPU
docker run --rm --gpus all nvidia/cuda:12.2.0-base-ubuntu22.04 nvidia-smi
```

### 1.2 克隆仓库并配置环境变量

```bash
git clone https://github.com/superLango/document-parser-rag-system.git
cd document-parser-rag-system

# 复制部署环境变量模板并编辑密钥
cp deploy/.env.example deploy/.env
vim deploy/.env
```

`deploy/.env` 中必须修改以下密钥项：

| 变量 | 说明 | 示例 |
|------|------|------|
| `POSTGRES_PASSWORD` | PostgreSQL 数据库密码 | `MyStr0ngP@ss` |
| `MINIO_ROOT_USER` | SeaweedFS S3 访问密钥 | `minioadmin` |
| `MINIO_ROOT_PASSWORD` | SeaweedFS S3 访问密钥密码 | `MyMinioP@ss` |
| `NEO4J_PASSWORD` | Neo4j 数据库密码 | `MyNeo4jP@ss` |
| `JWT_SECRET_KEY` | JWT 签名密钥（不少于 32 字符） | `a1b2c3d4e5f6...随机字符串` |

### 1.3 启动服务

```bash
# 在项目根目录执行，一键拉起全部服务
docker compose -f deploy/docker-compose.yml up -d
```

如需同时启动开发环境覆盖配置（端口映射、调试选项等）：

```bash
docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.override.yml up -d
```

### 1.4 等待健康检查并验证服务

各服务定义了健康检查（healthcheck），首次启动需等待模型加载与初始化完成：

```bash
# 查看各服务状态（等待所有显示 healthy）
docker compose -f deploy/docker-compose.yml ps

# 跟踪后端启动日志（等待 "Application startup complete"）
docker compose -f deploy/docker-compose.yml logs -f backend
```

验证服务可用性：

```bash
# 后端健康检查
curl http://localhost:8000/health
# 预期返回: {"status": "ok"}

# 前端页面
curl -I http://localhost
# 预期返回: HTTP/1.1 200 OK

# API 文档（Swagger UI）
curl -I http://localhost:8000/docs
```

首次启动时后端的 `start_period` 为 60 秒（模型加载），请耐心等待。

---

## 二、服务地址

部署完成后，各服务监听地址如下：

| 服务 | 端口 | URL | 默认凭证 |
|------|------|-----|----------|
| Frontend（前端） | 80 | http://localhost | - |
| Backend API（后端） | 8000 | http://localhost:8000 | - |
| PostgreSQL | 5432 | localhost:5432 | postgres / changeme |
| Valkey（Redis 兼容） | 6379 | localhost:6379 | - |
| SeaweedFS（S3 兼容） | 9000 | http://localhost:9000 | - |
| Neo4j | 7474 | http://localhost:7474 | neo4j / changeme |
| Milvus | 19530 | localhost:19530 | - |
| Prometheus | 9090 | http://localhost:9090 | - |
| Grafana | 3001 | http://localhost:3001 | admin / admin |

> **安全提示**：上表中的默认凭证仅适用于内网测试环境。生产部署时必须在 `deploy/.env` 中替换所有密码。

---

## 三、故障排查

### 3.1 GPU 未被检测到

**现象**：后端或 arq-worker 容器启动失败，日志中出现 `CUDA not available` 或 `No GPU found`。

**排查步骤**：

```bash
# 1. 确认宿主机 GPU 驱动正常
nvidia-smi

# 2. 确认 nvidia-container-toolkit 已安装
nvidia-ctk --version
# 若未安装：
# sudo apt-get install -y nvidia-container-toolkit
# sudo nvidia-ctk runtime configure --runtime=docker
# sudo systemctl restart docker

# 3. 确认容器内可访问 GPU
docker run --rm --gpus all nvidia/cuda:12.2.0-base-ubuntu22.04 nvidia-smi

# 4. 检查 docker-compose.yml 中 deploy.resources.reservations.devices 配置
# 确认 device_ids 与 capabilities 设置正确
```

### 3.2 后端无法启动

**现象**：`hansight-backend` 容器反复重启或健康检查失败。

**排查步骤**：

```bash
# 1. 查看后端日志
docker compose -f deploy/docker-compose.yml logs backend

# 2. 检查 .env 文件是否配置正确
cat deploy/.env
# 确认 POSTGRES_PASSWORD、JWT_SECRET_KEY 等已填写

# 3. 确认 PostgreSQL 已就绪
docker compose -f deploy/docker-compose.yml ps postgres
# 状态应为 healthy

# 4. 手动测试数据库连接
docker exec hansight-postgres pg_isready -U postgres -d docparser

# 5. 检查 DATABASE_URL 环境变量
docker exec hansight-backend env | grep DATABASE_URL
```

常见原因：`.env` 中密码未修改、PostgreSQL 尚未完成初始化、数据库连接字符串格式错误。

### 3.3 内存溢出（OOM）

**现象**：arq-worker 容器被系统 OOM Killer 杀死，`dmesg` 中出现 `Out of memory` 记录。

**解决方案**：

```bash
# 1. 减少并发任务数
# 编辑 backend/app/tasks/arq_worker.py，降低 max_jobs：
#   class WorkerSettings:
#       max_jobs = 2  # 默认值，按 GPU 显存调整

# 2. 限制容器内存使用（docker-compose.yml 中添加）
#   arq-worker:
#     deploy:
#       resources:
#         limits:
#           memory: 32G

# 3. 监控容器内存使用
docker stats hansight-arq-worker
```

### 3.4 Neo4j 内存不足

**现象**：Neo4j 容器启动失败或频繁重启。

**解决方案**：

调整 `deploy/docker-compose.yml` 中 Neo4j 的堆内存配置：

```yaml
neo4j:
  environment:
    # 根据宿主机可用内存调整
    NEO4J_server_memory_heap_initial__size: 4G   # 初始堆（默认 8G）
    NEO4J_server_memory_heap_max__size: 8G       # 最大堆（默认 16G）
    NEO4J_server_memory_pagecache_size: 4G       # 页面缓存（默认 8G）
```

### 3.5 Milvus 连接失败

**现象**：后端日志中出现 `Milvus connection refused` 或 `Milvus not ready`。

**排查步骤**：

```bash
# 1. 确认 etcd 健康检查通过（Milvus 依赖 etcd）
docker compose -f deploy/docker-compose.yml ps etcd
# 状态应为 healthy

# 2. 确认 SeaweedFS 健康检查通过（Milvus 依赖对象存储）
docker compose -f deploy/docker-compose.yml ps seaweedfs

# 3. Milvus 首次启动较慢，等待健康检查通过
docker compose -f deploy/docker-compose.yml ps milvus
# 状态应为 healthy

# 4. 查看 Milvus 日志
docker compose -f deploy/docker-compose.yml logs milvus
```

Milvus 依赖 etcd 与 SeaweedFS，两者均健康后 Milvus 才能正常启动。首次启动可能需要 1-2 分钟。

---

## 四、开发环境

### 4.1 后端开发

```bash
cd backend
source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

- API 文档：http://localhost:8000/docs
- 热重载：代码修改后自动生效（`--reload` 参数）
- 数据库：PostgreSQL at `localhost:5432`（需先启动基础设施服务）

### 4.2 前端开发

```bash
cd frontend
pnpm install
pnpm dev
```

- 开发服务器地址：http://localhost:5174
- API 代理：开发环境通过 Vite 代理转发至后端 `localhost:8000`

### 4.3 数据库

开发环境使用与生产相同的 PostgreSQL 实例（通过 Docker 部署）：

```
Host: localhost
Port: 5432
Database: docparser
Username: postgres
Password: deploy/.env 中 POSTGRES_PASSWORD 的值
```

数据库迁移：

```bash
cd backend
alembic upgrade head    # 应用所有迁移
alembic revision --autogenerate -m "描述"  # 生成新迁移
```

### 4.4 默认管理员

系统预置管理员账号用于首次登录：

| 字段 | 值 |
|------|-----|
| 用户名 | admin |
| 密码 | admin123 |

> **安全提示**：首次登录后请立即修改默认密码。

---

## 五、目录结构说明

```
doc_parse_project/
├── backend/                         # 后端服务（FastAPI）
│   ├── app/
│   │   ├── main.py                 # 应用入口，注册路由与中间件
│   │   ├── core/                    # 核心模块：配置、数据库、安全、日志、异常、响应
│   │   ├── api/v1/endpoints/       # API 端点：auth、documents、dashboard、schemas、terms 等
│   │   ├── models/                  # SQLAlchemy ORM 模型
│   │   ├── schemas/                 # Pydantic 请求/响应模型
│   │   ├── services/                # 业务逻辑层：OCR、抽取、分块、嵌入、检索、图谱
│   │   └── tasks/                   # arq 异步任务：文档解析、向量入库、图谱构建
│   ├── alembic/                     # 数据库迁移脚本
│   ├── tests/                       # pytest 测试套件
│   ├── requirements.txt
│   └── Dockerfile
│
├── frontend/                        # 前端服务（Vue 3 + TypeScript）
│   ├── src/
│   │   ├── api/                     # API 接口封装
│   │   ├── views/                   # 页面组件
│   │   ├── stores/                  # Pinia 状态管理
│   │   ├── router/                  # Vue Router 路由
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
│   └── DEPLOYMENT.md                # 本文档
│
├── scripts/                         # 运维脚本
│   └── init_db.sql                  # 数据库初始化 SQL
│
└── models/                          # AI 模型文件（OCR / 嵌入 / 重排）
    ├── bge-m3/                      # BGE 嵌入模型
    ├── bge-reranker-v2-m3/          # BGE 重排模型
    ├── MinerU-Popo/                  # 版面分析模型
    └── PaddlePaddle/PaddleOCR-VL/   # OCR 识别模型
```

### 核心目录说明

- **backend/app/api/v1/endpoints/**：REST API 端点，按资源拆分（auth、documents、dashboard、schemas、terms、knowledge_graph、qa 等），所有接口统一挂载在 `/api/v1` 前缀下。
- **backend/app/services/**：业务逻辑层，封装 OCR 识别、版面分析、结构化抽取、文本分块、向量嵌入、知识图谱构建、RAG 检索等核心能力。
- **backend/app/tasks/**：arq 异步任务定义，处理文档解析、向量入库、图谱构建等长耗时操作，通过 Valkey 消息队列调度。
- **deploy/**：Docker Compose 编排文件与各中间件配置，支持一键拉起全部服务。
