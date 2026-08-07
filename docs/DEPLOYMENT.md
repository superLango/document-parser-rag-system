# 部署指南

> 本文档描述 HansonDOC RAG 的完整部署流程，涵盖**资源部署**（基础设施服务）、**模型部署**（AI 模型 + vLLM 推理服务）与**应用部署**（后端 API + arq worker + 前端）。

---

## 目录

1. [部署概述](#1-部署概述)
2. [环境前提](#2-环境前提)
3. [资源部署（基础设施）](#3-资源部署基础设施)
4. [模型部署（AI 模型 + vLLM）](#4-模型部署ai-模型--vllm)
5. [应用部署](#5-应用部署)
6. [部署验证](#6-部署验证)
7. [服务地址总表](#7-服务地址总表)
8. [故障排查](#8-故障排查)

---

## 1. 部署概述

HansonDOC RAG 采用**裸机 + GPU 直跑**部署模式：

- **AI 推理服务**（vLLM）与**应用服务**（FastAPI / arq worker）直接运行于宿主机，以充分利用 GPU 显存与 CPU
- **基础设施服务**（PostgreSQL / Redis / MinIO / Milvus / NebulaGraph）可原生安装或容器化运行
- 全组件内网运行，数据不出网

### 部署顺序

```
1. 资源部署（基础设施服务）
       ↓
2. 模型部署（下载模型 + 启动 vLLM）
       ↓
3. 应用部署（后端 + worker + 前端）
       ↓
4. 部署验证
```

---

## 2. 环境前提

| 依赖 | 最低版本 | 说明 |
|------|----------|------|
| NVIDIA Driver | 535+ | GPU 驱动，需支持 CUDA 12.x |
| CUDA Toolkit | 12.x | 编译 PyTorch / vLLM 所需 |
| Python | 3.12+ | 后端 + vLLM |
| Node.js | 20+ | 前端 |
| pnpm | 10+ | 前端包管理 |
| PostgreSQL | 16 | 元数据存储 |
| Redis | 7+ | 缓存 + 任务队列 |

### GPU 验证

```bash
# 确认 GPU 驱动与显存
nvidia-smi

# 确认 CUDA 可用
python -c "import torch; print('CUDA:', torch.cuda.is_available(), 'Devices:', torch.cuda.device_count())"
```

> 建议显存 ≥ 120G（运行 Qwen3.6-35B-A3B-FP8 + GLM-OCR + Popo + 嵌入/重排模型）。最低 40G 可降级运行较小模型。

---

## 3. 资源部署（基础设施）

### 3.1 PostgreSQL 16

原生安装（推荐）或容器化：

```bash
# Ubuntu 原生安装
sudo apt install postgresql-16

# 创建数据库与用户
sudo -u postgres psql <<'SQL'
CREATE USER docparser WITH PASSWORD '你的强密码';
CREATE DATABASE docparser OWNER docparser;
SQL
```

配置 `pg_hba.conf` 允许本地连接，监听 `5432`。

### 3.2 Redis

```bash
# 原生安装
sudo apt install redis-server

# 验证（db0 缓存，db1 arq 任务队列）
redis-cli ping   # PONG
```

监听 `6379`，无需密码（内网部署）或按需配置 ACL。

### 3.3 MinIO（S3 兼容对象存储）

```bash
# 容器化运行
docker run -d --name minio \
  -p 9000:9000 -p 9001:9001 \
  -v /home/hanson/doc_parse_project/volumes/minio:/data \
  -e MINIO_ROOT_USER=minioadmin \
  -e MINIO_ROOT_PASSWORD=你的强密码 \
  minio/minio server /data --console-address ":9001"
```

- API 端口 `9000`，控制台 `9001`
- KB 专属 bucket（`kb-{kb_id}`）由应用首次创建 KB 时自动创建

### 3.4 Milvus 2.4（+ etcd）

Milvus standalone 依赖 etcd 与对象存储：

```bash
# etcd
docker run -d --name etcd \
  -p 2379:2379 \
  -v /home/hanson/doc_parse_project/volumes/etcd:/etcd-data \
  quay.io/coreos/etcd:v3.5.5 \
  etcd -name etcd -data-dir /etcd-data

# Milvus standalone
docker run -d --name milvus \
  -p 19530:19530 -p 9091:9091 \
  -v /home/hanson/doc_parse_project/volumes/milvus:/var/lib/milvus \
  milvusdb/milvus:v2.4.0 milvus run standalone
```

- API 端口 `19530`，健康检查 `9091`
- 首次启动需 1-2 分钟初始化

> Milvus 配置可参考 `deploy/milvus_config/` 目录。

### 3.5 NebulaGraph

NebulaGraph 由 graphd / storaged / metad 三个组件组成：

```bash
# 使用官方 docker-compose 或手动启动三组件
# graphd 端口 9669（客户端连接），metad 9559，storaged 9779
docker run -d --name nebula-graphd -p 9669:9669 ... vesoft/nebula-graphd
docker run -d --name nebula-metad   -p 9559:9559 ... vesoft/nebula-metad
docker run -d --name nebula-storaged -p 9779:9779 ... vesoft/nebula-storaged
```

- 客户端连接 graphd 端口 `9669`
- **DDL 异步生效**：CREATE SPACE/TAG/EDGE/INDEX 后需轮询等待，应用层已实现重试机制
- 默认凭证：`root` / `nebula`（生产环境必须修改）

### 3.6 基础设施验证

```bash
psql -h localhost -U docparser -d docparser -c "SELECT 1"   # PostgreSQL
redis-cli ping                                                # Redis
curl http://localhost:9000/minio/health/live                  # MinIO
curl http://localhost:9091/healthz                            # Milvus
# NebulaGraph: 通过应用 /system/check-nebula-graph 接口验证
```

---

## 4. 模型部署（AI 模型 + vLLM）

### 4.1 下载 AI 模型

```bash
cd /home/hanson/doc_parse_project
python scripts/download_model.py
```

使用 HF 镜像（hf-mirror.com）下载，ModelScope 作为回退。下载至 `models/` 目录：

| 模型目录 | 用途 | 大小 |
|----------|------|------|
| `models/bge-m3/` | 五维文本嵌入 | ~4.3G |
| `models/bge-reranker-v2-m3/` | CrossEncoder 精排 | ~2.2G |
| `models/gliclass-multilang-mini/` | 零样本类别分类 | ~557M |
| `models/glm-ocr/` | 主 OCR 引擎 | ~2.5G |
| `models/Qwen/Qwen3.6-35B-A3B-FP8/` | 主 LLM | ~66G |
| `models/MinerU-Popo/` | 版面分析后处理 | ~17G |
| `models/PaddlePaddle/` | 备选 OCR | ~2.0G |

### 4.2 创建 vLLM 虚拟环境

vLLM 推荐独立虚拟环境（避免与后端依赖冲突）：

```bash
cd /home/hanson/doc_parse_project
python -m venv venv_model
source venv_model/bin/activate
pip install vllm
```

### 4.3 启动 vLLM 推理服务

系统运行**三个 vLLM 服务**，需在 GPU 显存预算内分配 `gpu-memory-utilization`：

#### 4.3.1 GLM-OCR 服务（端口 9977）

```bash
cd /home/hanson/doc_parse_project
source venv_model/bin/activate
vllm serve ./models/glm-ocr \
  --host 0.0.0.0 --port 9977 \
  --served-model-name GLM-OCR \
  --trust-remote-code \
  --max-num-seqs 2 \
  --max-num-batched-tokens 8192 \
  --max-model-len 32768 \
  --enable-prefix-caching \
  --enable-chunked-prefill \
  --gpu-memory-utilization 0.16
```

#### 4.3.2 Qwen3.6-35B 主 LLM 服务（端口 9988）

```bash
vllm serve ./models/Qwen/Qwen3.6-35B-A3B-FP8 \
  --host 0.0.0.0 --port 9988 \
  --served-model-name Qwem3.6-35B-A3B-FP8 \
  --kv-cache-dtype fp8 \
  --trust-remote-code \
  --max-model-len 55000 \
  --max-num-seqs 8 \
  --max-num-batched-tokens 27500 \
  --gpu-memory-utilization 0.40 \
  --enable-prefix-caching
```

#### 4.3.3 MinerU-Popo 服务（端口 9999）

```bash
vllm serve ./models/MinerU-Popo \
  --host 0.0.0.0 --port 9999 \
  --served-model-name Popo \
  --max-model-len 32768 \
  --gpu-memory-utilization 0.10 \
  --max-num-seqs 2
```

> **显存分配**：0.16 + 0.40 + 0.10 = 0.66，剩余约 34% 供 arq worker 内加载的 bge-m3 / bge-reranker / gliclass 模型使用。

### 4.4 模型服务验证

```bash
# GLM-OCR
curl http://localhost:9977/v1/models

# Qwen LLM
curl http://localhost:9988/v1/models

# Popo
curl http://localhost:9999/v1/models
```

> **关键约束**：`--served-model-name` 必须与 `backend/.env` 中的 `LLM_API_MODEL` / `GLMOCR_MODEL` / `EXTRACTION_MODEL_ID` 完全一致，否则调用 404。

---

## 5. 应用部署

### 5.1 配置环境变量

```bash
cp backend/.env.example backend/.env
vim backend/.env
```

必须配置的关键项：

| 变量 | 说明 |
|------|------|
| `POSTGRES_PASSWORD` / `DATABASE_URL` | PostgreSQL 密码与连接串 |
| `REDIS_URL` | Redis 连接（db0 缓存） |
| `MINIO_ENDPOINT` / `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` | MinIO 连接 |
| `NEBULA_GRAPHD_HOST` / `NEBULA_USER` / `NEBULA_PASSWORD` | NebulaGraph 连接 |
| `MILVUS_HOST` / `MILVUS_PORT` | Milvus 连接 |
| `SECRET_KEY` | JWT 签名密钥（≥32 字符） |
| `LLM_API_BASE` / `LLM_API_MODEL` | 主 LLM vLLM 端点（9988） |
| `GLMOCR_SERVER_URL` / `GLMOCR_MODEL` | GLM-OCR vLLM 端点（9977） |
| `EXTRACTION_API_BASE` / `EXTRACTION_MODEL_ID` | 抽取 LLM 端点（通常同 9988） |
| `EMBEDDING_MODEL_PATH` | bge-m3 模型路径 |
| `PUBLIC_KB_ID` | 公开一体化接口默认知识库 ID（可选） |

> 完整配置项说明见 [CONFIGURATION.md](CONFIGURATION.md)。

### 5.2 后端 API 服务

```bash
cd /home/hanson/doc_parse_project/backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 应用数据库迁移
alembic upgrade head

# 启动 API（监听 8000）
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

- API 文档：http://localhost:8000/docs
- 健康检查：http://localhost:8000/health

### 5.3 arq 异步 worker

worker 负责执行 OCR、抽取、图谱构建等长耗时任务，需配置 CUDA 环境：

```bash
cd /home/hanson/doc_parse_project/backend
./start_worker.sh
```

`start_worker.sh` 已内置：

- 激活 `venv` 虚拟环境
- 设置 `CUDA_VISIBLE_DEVICES=0` / `CUDA_HOME` / `LD_LIBRARY_PATH`
- 验证 torch CUDA 可用
- 启动 `arq app.tasks.arq_worker.WorkerSettings`

> worker 进程内加载 bge-m3 / bge-reranker / gliclass 模型，占用剩余 GPU 显存。

### 5.4 前端服务

```bash
cd /home/hanson/doc_parse_project/frontend
pnpm install
pnpm dev          # 开发模式，端口 5174
# 或 pnpm build && pnpm preview  # 生产构建
```

- 开发地址：http://localhost:5174
- API 代理：Vite 开发代理转发至后端 `localhost:8000`

### 5.5 进程守护（生产建议）

生产环境建议用 systemd / supervisor 守护以下进程：

- `uvicorn app.main:app`（API）
- `arq app.tasks.arq_worker.WorkerSettings`（worker）
- 3 个 `vllm serve`（推理服务）
- `pnpm preview` 或 nginx 托管前端构建产物（前端）

---

## 6. 部署验证

### 6.1 服务健康检查

```bash
curl http://localhost:8000/health                          # 后端
curl http://localhost:8000/api/v1/system/health             # 系统健康
curl http://localhost:8000/api/v1/system/health/models      # 模型健康
curl http://localhost:8000/api/v1/system/health/storage     # 存储健康
```

### 6.2 端到端验证

1. 访问前端 http://localhost:5174，使用默认管理员登录（admin / admin123）
2. 创建知识库 → 应用领域模板 → 配置 Schema/Prompt/术语集/LLM 端点
3. 上传 PDF 文档 → 触发解析 → 查看抽取结果
4. 测试 RAG 问答

### 6.3 公开一体化接口验证

```bash
# 上传
curl -X POST http://localhost:8000/api/v1/public/extraction/upload \
  -F "file=@test.pdf" -F "kb_id=<已配置的KB_ID>"

# 轮询状态（用返回的 task_id）
curl http://localhost:8000/api/v1/public/extraction/<task_id>/status

# 获取结果
curl http://localhost:8000/api/v1/public/extraction/<task_id>/result

# 预览源文件
curl http://localhost:8000/api/v1/public/extraction/<task_id>/preview
```

---

## 7. 服务地址总表

| 服务 | 端口 | 地址 | 凭证 |
|------|------|------|------|
| 前端（开发） | 5174 | http://localhost:5174 | - |
| 后端 API | 8000 | http://localhost:8000 | - |
| API 文档 | 8000 | http://localhost:8000/docs | - |
| PostgreSQL | 5432 | localhost:5432 | docparser / .env |
| Redis | 6379 | localhost:6379 | - |
| MinIO API | 9000 | http://localhost:9000 | .env |
| MinIO 控制台 | 9001 | http://localhost:9001 | .env |
| Milvus | 19530 | localhost:19530 | - |
| NebulaGraph graphd | 9669 | localhost:9669 | root / .env |
| vLLM GLM-OCR | 9977 | http://localhost:9977/v1 | - |
| vLLM Qwen LLM | 9988 | http://localhost:9988/v1 | - |
| vLLM Popo | 9999 | http://localhost:9999/v1 | - |
| Prometheus 指标 | 8000 | http://localhost:8000/metrics | - |

> 默认凭证仅适用于内网测试环境，生产部署必须在 `.env` 中替换所有密码。

---

## 8. 故障排查

### 8.1 GPU 未被检测到

```bash
nvidia-smi                                              # 宿主机驱动
python -c "import torch; print(torch.cuda.is_available())"  # torch CUDA
# worker 报 CUDA 错误：检查 start_worker.sh 的 LD_LIBRARY_PATH 是否设置
```

### 8.2 vLLM 服务 404 / 模型未找到

- 确认 `--served-model-name` 与 `.env` 中 `LLM_API_MODEL` / `GLMOCR_MODEL` 完全一致（大小写敏感）
- 确认 `curl http://localhost:9988/v1/models` 返回预期模型名

### 8.3 后端无法启动

```bash
# 查看日志，常见原因：
# - .env 密码未修改 / DATABASE_URL 格式错误
# - PostgreSQL 未就绪
# - 数据库迁移未应用（alembic upgrade head）
docker exec -it <pg容器> pg_isready -U docparser -d docparser
```

### 8.4 arq worker 任务不执行

```bash
# 确认 worker 进程存活
ps aux | grep arq

# 确认 Redis db1 队列可用（arq 使用 database=1）
redis-cli -n 1 keys "arq:*"

# worker 启动失败常见原因：
# - CUDA 环境变量缺失（LD_LIBRARY_PATH）
# - 模型路径错误（EMBEDDING_MODEL_PATH）
# - Redis 连接失败（提交任务时报"任务队列服务不可用"）
```

### 8.5 Milvus 连接失败

```bash
# Milvus 依赖 etcd 与对象存储，需两者均健康
docker ps | grep -E "etcd|milvus"
docker logs milvus --tail 50
# 首次启动较慢，等待 1-2 分钟
```

### 8.6 NebulaGraph "Schema not exist"

- DDL 异步生效，CREATE SPACE/TAG/EDGE/INDEX 后不立即可用
- 应用层已实现重试（3 次 × 2 秒间隔），偶发可重试任务
- 确认 storaged 已 `ADD HOSTS` 并状态为 ONLINE

### 8.7 内存溢出（OOM）

- arq worker 加载多模型，内存占用较高
- 降低 `EXTRACTION_MAX_CONCURRENCY` / `EXTRACTION_V3_LLM_MAX_CONCURRENCY`
- 用 systemd 限制 worker 内存并配置 `Restart=on-failure`

### 8.8 公开接口"任务队列服务不可用"

- arq worker 未启动或 Redis db1 不可达
- 上传接口 `_get_arq_pool` 连接失败即抛此错误（不静默失败）
