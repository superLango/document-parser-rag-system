# Docker 镜像构建方案 v3（hansonDoc_RAG · 全容器化）

> 版本：v3.1 · 2026-08-23 · 状态：已执行（模型卷挂载方案）
> 已确认：① 模型进镜像 ② python:3.13-slim + torch cu130 ③ GPU ④ 前端非常用端口 ⑤ 依赖服务全部容器化（含 PostgreSQL） ⑥ 预热保留但跳过 OCR/LLM ⑦ vLLM 9977/9988

## 一、目标架构（全容器化）

应用 + 小模型（嵌入/重排/版面）+ 依赖服务（PostgreSQL/Redis/MinIO）全部容器化；**OCR（GLM-OCR）与 LLM 由宿主机 vLLM 独立运行**，容器通过 env 指向。

```
┌────────────────────────────────────────────────────────────────┐
│ 宿主机（NVIDIA GB10 / CUDA 13.0 / Docker + nvidia-container）     │
│                                                                │
│  docker-compose（6 服务）                                        │
│  ├─ postgres（pgvector）── 数据初始化：仅保留航天航空 KB            │
│  ├─ redis（队列）                                               │
│  ├─ minio（对象存储 + bucket 初始化）                            │
│  ├─ hansondoc-backend（uvicorn :8000）── GPU                    │
│  ├─ hansondoc-worker （arq 异步任务）────── GPU                  │
│  └─ hansondoc-frontend（nginx）                                 │
│                                                                │
│  vLLM 独立进程（非容器）：                                        │
│  GLM-OCR :9977 · LLM :9988（容器 env 指向宿主 IP）               │
└────────────────────────────────────────────────────────────────┘
```

## 二、镜像构建

### 2.1 后端镜像 `hansondoc-backend`

| 内容 | 说明 |
|---|---|
| 基础镜像 | `python:3.13-slim`，pip 安装 `torch==2.13.0+cu130` / `torchvision==0.28.0`（cu130 wheel，已验证 GB10 可用） |
| Python 依赖 | `backend/requirements.txt` 全量（fastapi/sqlalchemy[asyncio]/asyncpg/alembic/arq/minio/pgvector/structlog/…）+ `croniter` + transformers 5.15 + ultralytics 8.1.47 + doclayout_yolo + pymupdf + opencv + Pillow + jieba |
| **小模型权重** | **不入镜像**（离线部署体积考虑）：由宿主机 `models/` 目录卷挂载到 `/app/models`（bge-m3 2.6G / bge-reranker-v2-m3 2.2G / pp_doclayoutv3 128M，约 5G） |
| 应用代码 | `backend/` → `/app/backend`（含 alembic 迁移与全部服务） |
| 入口 | `entrypoint.sh`：等待 PG 就绪 → `alembic upgrade head` → 启动 uvicorn / arq（按 command） |
| GPU | 运行需 NVIDIA 容器运行时（embedding/reranker/layout 均 CUDA） |

**不打包**：`bge-reranker-base`（3.2G 未用）、`pp_doclayoutv2`（205M 已弃用）、`doclayout_yolo`（38M 旧方案）。

### 2.2 前端镜像 `hansondoc-frontend`

| 阶段 | 内容 |
|---|---|
| 构建 | `node:20-alpine`：`pnpm install --frozen-lockfile` + `vite build` → `dist` |
| 运行 | `nginx:alpine`：托管 `dist`，`/api/` 反代 `hansondoc-backend:8000` |

### 2.3 依赖服务镜像（compose 内置）

| 服务 | 镜像 | 端口（宿主） | 说明 |
|---|---|---|---|
| postgres | `pgvector/pgvector:pg18`（与现有 PG 18.4 一致；若官方暂未发布 pg18 标签则回退 pg17） | **15432**（避开系统 5432） | 数据初始化见第五节 |
| redis | `redis:7-alpine` | **16379**（避开系统 6379） | arq 队列 |
| minio | `minio/minio` | **19000/19001**（避开系统 9000） | 对象存储，启动时 `mc` 初始化 bucket（`hansondoc-*`） |

## 三、docker-compose 服务

| 服务 | 镜像 | 命令 | 端口 | GPU |
|---|---|---|---|---|
| postgres | pgvector/pgvector:pg18 | 默认 | 15432 | - |
| redis | redis:7-alpine | 默认 | 16379 | - |
| minio | minio/minio | server /data | 19000/19001 | - |
| backend | hansondoc-backend | `uvicorn app.main:app --host 0.0.0.0 --port 8000` | **18000** | ✅ |
| worker | hansondoc-backend | `arq app.tasks.arq_worker.WorkerSettings` | - | ✅ |
| frontend | hansondoc-frontend | nginx | **18080** | - |

`TASK_EXECUTOR=arq`（生产异步执行）。外部系统对接接口走 backend `18000`，页面走 frontend `18080`。

## 四、环境变量（.env）

```ini
# 应用
TASK_EXECUTOR=arq
MODEL_WARMUP_ENABLED=true
MODEL_WARMUP_SKIP_EXTERNAL=true   # 预热仅嵌入/重排/版面，跳过 OCR/LLM（需小改 model_warmup）

# PostgreSQL（容器）
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_DB=hanson_doc_rag
POSTGRES_USER=hansondoc
POSTGRES_PASSWORD=******

# Redis（容器）
REDIS_URL=redis://redis:6379/0

# MinIO（容器）
MINIO_ENDPOINT=minio:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin

# OCR / LLM（宿主 vLLM，容器经 host.docker.internal 访问）
GLMOCR_SERVER_URL=http://host.docker.internal:9977/v1/chat/completions
LLM_SERVER_URL=http://host.docker.internal:9988/v1
LLM_SERVER_MODEL=Qwen3.6-35B-A3B-FP8

# 模型路径（镜像内）
EMBEDDING_MODEL_DIR=/app/models/bge-m3
RERANKER_MODEL_DIR=/app/models/bge-reranker-v2-m3
PARSEKIT_LAYOUT_MODEL_DIR=/app/models/pp_doclayoutv3_finetuned_v1
```

`extra_hosts: host.docker.internal:host-gateway`（backend/worker 添加，访问宿主机 vLLM）。

## 五、数据初始化（PostgreSQL 容器）

**目标**：容器 PostgreSQL 中保留系统基础数据 + 「航天航空检测知识库」（`25e7d8ef-...`）的**抽取配置与术语集**；**文档及其向量数据清空**（可重新上传解析构建），其他知识库清除。

### 现状数据量（实测）

| 表 | 航天航空 KB | 全库 |
|---|---|---|
| knowledge_bases | 1 | **259** |
| documents | 17 | 111 |
| document_chunks / text_chunks | 433 / 433 | 465 / 465 |
| terms / term_bases | 967 / 3 | 1074 / 120 |
| schema_templates / categories / fields | 1 / 3 / 27 | 67 / 87 / 74 |
| prompt_templates / content | 2 / 4 | 48 / 76 |
| rule_groups / items / scripts | 1 / 7 / 5 | 20 / 21 / 47 |
| kb_extraction_config | 1 | 6 |
| extraction_results | 8 | 10 |
| kb_members | 1 | 289 |

### 初始化流程

1. **导出**（执行时在宿主机跑）：`pg_dump` 全库（schema + data）→ `backup/dump.sql`（含 alembic_version，保证迁移版本一致）；
2. **PG 容器首次启动**（挂载 `/docker-entrypoint-initdb.d/`）：
   - `01-init.sql`：`CREATE EXTENSION vector;`
   - `02-restore.sql`：`psql` 恢复 `dump.sql`（全量恢复）；
   - `03-clean.sql`：**清理脚本**（superuser 执行，绕过 RLS）：
     - `TRUNCATE task_outbox, task_dead_letter, integration_tasks;`（历史任务清空，避免 arq 重复消费）
     - `DELETE FROM knowledge_bases WHERE id <> '25e7d8ef-...';`（FK 级联清理其他 258 个 KB 的文档/分块/Schema/术语/抽取结果/成员等）
     - `DELETE FROM kb_invitations;`（无航天航空邀请数据）
     - 校验：清理后仅剩 1 个知识库、系统表数据完整；
3. **backend 启动**：`alembic upgrade head`（幂等，确保迁移最新）→ 启动。

**保留（系统表全量）**：users / roles / permissions / role_permissions / user_roles / workspaces / workspace_members / groups / audit_logs / api_keys / password_history（保证登录与权限可用）。

**保留（航天航空 KB 配置资产）**：
- `knowledge_bases`（仅 `25e7d8ef-...`）+ `kb_members`
- 抽取配置：`schema_templates / schema_categories / schema_fields / prompt_templates / prompt_content / rule_groups / rule_group_items / kb_scripts / kb_extraction_config`
- 术语集：`term_bases / terms`（967 条）

**清空（文档与向量，重新上传后重建）**：
- `documents / document_chunks / text_chunks / kb_bm25_stats / extraction_results / extraction_history`
- 任务与队列：`document_tasks / task_outbox / task_dead_letter / integration_tasks`

**清除（其他知识库）**：`DELETE FROM knowledge_bases WHERE id <> '25e7d8ef-...'`（级联清理其配置/术语/成员等）。

## 六、预热调整（需改代码）

[model_warmup.py](/home/grainuser/hansonDoc_RAG/backend/app/services/model_warmup.py) 增加配置 `MODEL_WARMUP_SKIP_EXTERNAL`（默认 false）：为 true 时 `warmup_all` 只预热 `embedding / reranker / layout`，**跳过 `llm_qwen / glm_ocr`**（外部 vLLM 不预热）。

## 七、构建产物清单

1. `backend/Dockerfile` + `backend/entrypoint.sh`
2. `frontend/Dockerfile` + `frontend/nginx.conf`
3. `docker-compose.yml`（6 服务 + GPU + env + host-gateway）
4. `deploy/initdb/01-init.sql`、`02-restore.sql`、`03-clean.sql`
5. `.env.example`
6. `scripts/db_export.sh`（pg_dump 导出）、`scripts/docker_build.sh`、`scripts/docker_deploy.sh`
7. `docs/DOCKER_DEPLOY.md`（部署手册：GPU 运行时、vLLM 启动、初始化校验、验证步骤）

## 八、镜像体积估算

| 镜像 | 组成 | 估算 |
|---|---|---|
| hansondoc-backend | torch(cu130)+transformers+ultralytics 等依赖 | **≈ 6.7G（不含模型，模型卷挂载约 5G）** |
| hansondoc-frontend | nginx + 静态 | ≈ 50M |

## 九、部署步骤（概要）

1. 安装 Docker + nvidia-container-toolkit（宿主已具备 GPU 驱动）；
2. 宿主机启动 vLLM：GLM-OCR（9977）、LLM（9988）；
3. 执行 `scripts/db_export.sh` 生成 `backup/dump.sql`；
4. `docker build` 两个镜像（或 `docker_build.sh`）；
5. `docker compose up -d`（首次 PG 自动初始化数据）；
6. 校验：登录、航天航空 KB 数据完整、OCR/抽取链路、对接接口。

## 十、待确认点（v2 补充）

1. **PG 容器版本**：`pgvector/pgvector:pg18`（与现有 PG 18.4 一致；官方若无 pg18 标签则回退 pg17），确认？
2. **端口**：frontend **18080** / backend **18000** / PG **15432** / Redis **16379** / MinIO **19000**（均避开系统实例端口），确认？
3. **数据初始化**：pg_dump 全量 → 恢复 → 清理：
   - 保留系统表全量 + 航天航空 KB 的**抽取配置与术语集**；
   - **清空文档/向量**（documents、chunks、BM25、抽取结果）与任务表；
   - 删除其余 258 个知识库；
   确认？
4. **MinIO bucket 初始化**：启动时自动建 `hansondoc-*` bucket，确认？
5. **预热**：`MODEL_WARMUP_SKIP_EXTERNAL=true` 跳过 OCR/LLM 预热（需改 model_warmup.py），确认？
