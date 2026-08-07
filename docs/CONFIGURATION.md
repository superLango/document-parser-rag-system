# 配置与运维文档

> 本文档描述 HansonDOC RAG 的配置体系、抽取配置中心、领域模板、Hook 机制、数据库迁移与日常运维。

---

## 目录

1. [配置体系总览](#1-配置体系总览)
2. [环境变量参考](#2-环境变量参考)
3. [抽取配置中心](#3-抽取配置中心)
4. [领域模板](#4-领域模板)
5. [Hook 机制](#5-hook-机制)
6. [数据库迁移](#6-数据库迁移)
7. [日志与监控](#7-日志与监控)
8. [日常运维](#8-日常运维)
9. [关键约束与最佳实践](#9-关键约束与最佳实践)

---

## 1. 配置体系总览

系统采用**三层配置覆盖**机制，从全局到 KB 到运行时逐层细化：

```
全局 settings (backend/.env)   →   KB config JSON   →   Hook 脚本
       ↓                                ↓                    ↓
   引擎默认值                      KB 自定义配置        运行时动态覆盖
```

| 层级 | 位置 | 作用域 | 说明 |
|------|------|--------|------|
| 全局 | `backend/.env` → `app/core/config.py` | 全系统 | 引擎级默认值（端口、模型路径、并发、安全策略） |
| KB 配置 | `kb_extraction_config` JSON | 单个 KB | Schema / Prompt / 术语集 / LLM 端点 / 检索参数 |
| Hook | `kb_hooks/{kb_id}/hooks.py` | 单个 KB | 运行时动态覆盖（候选抽取/类别构建/校验/后处理） |

**核心原则**：消除所有硬编码，提交任务前全量显式配置校验，无静默回退。

---

## 2. 环境变量参考

环境变量通过 `backend/.env` 注入，由 `pydantic-settings` 加载为 `app.core.config.settings`。完整模板见 `backend/.env.example`。

### 2.1 应用基础

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `APP_NAME` | Hansight | 应用名称 |
| `APP_ENV` | development | 运行环境 |
| `DEBUG` | true | 调试模式 |
| `CORS_ORIGINS` | * | CORS 来源（生产应严格限定） |
| `ADMIN_IP_WHITELIST` | (空) | 管理端 IP 白名单 |

### 2.2 数据库与缓存

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `POSTGRES_HOST` / `POSTGRES_PORT` | localhost / 5432 | PostgreSQL |
| `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` | docparser / postgres / change_me | PostgreSQL 凭证 |
| `DATABASE_URL` | postgresql+asyncpg://... | 异步连接串 |
| `REDIS_URL` | redis://localhost:6379/0 | Redis（db0 缓存，db1 arq 队列） |

### 2.3 对象存储与图数据库

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MINIO_ENDPOINT` / `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` | localhost:9000 / ... | MinIO S3 兼容存储 |
| `KB_MINIO_BUCKET_PREFIX` | kb- | KB bucket 命名前缀 |
| `NEBULA_GRAPHD_HOST` / `NEBULA_GRAPHD_PORT` | localhost / 9669 | NebulaGraph |
| `NEBULA_USER` / `NEBULA_PASSWORD` | root / nebula | NebulaGraph 凭证 |
| `NEBULA_SPACE_PREFIX` | kb_ | KB graph space 前缀 |

### 2.4 向量库

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MILVUS_HOST` / `MILVUS_PORT` | localhost / 19530 | Milvus |
| `FIVE_DIM_VECTOR_COLLECTION` | doc_five_dim | 五维向量 Collection 基名 |
| `VECTOR_CHILD_MAX_CHARS` | 2000 | 子块最大字符数 |

### 2.5 AI 模型与 vLLM

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `EMBEDDING_MODEL_PATH` | .../models/bge-m3 | bge-m3 嵌入模型路径 |
| `EMBEDDING_BATCH_SIZE` | 16 | 嵌入批量大小 |
| `LLM_API_BASE` | http://localhost:9988/v1 | 主 LLM vLLM 端点 |
| `LLM_API_MODEL` | Qwem3.6-35B-A3B-FP8 | 主 LLM 模型名（须与 vLLM served-model-name 一致） |
| `GLMOCR_SERVER_URL` | http://localhost:9977/v1 | GLM-OCR vLLM 端点 |
| `GLMOCR_MODEL` | glm-ocr | GLM-OCR 模型名 |
| `GLMOCR_MODE` | fullpage | OCR 模式（fullpage 推荐） |
| `GLMOCR_MAX_CONCURRENCY` | 12 | GLM-OCR 并发上限 |
| `RERANKER_MODEL_DIR` | models/bge-reranker-v2-m3 | 重排模型路径 |
| `GLICLASS_MODEL_PATH` | models/gliclass-multilang-mini | 类别分类模型路径 |

### 2.6 抽取配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `EXTRACTION_PROVIDER` | openai | 抽取 LLM provider（openai 兼容 vLLM） |
| `EXTRACTION_API_BASE` | http://localhost:9988/v1 | 抽取 LLM 端点 |
| `EXTRACTION_MODEL_ID` | Qwem3.6-35B-A3B-FP8 | 抽取模型 ID |
| `EXTRACTION_MAX_CONCURRENCY` | 12 | 多类别并行并发上限 |
| `EXTRACTION_MAX_OUTPUT_TOKENS` | 32768 | 单次生成最大 token |
| `EXTRACTION_MAX_CHAR_BUFFER` | 20000 | LangExtract 分块字符上限 |
| `EXTRACTION_RECALL_CLASSIFY_FILTER_ENABLED` | true | gliclass 类别过滤开关 |
| `EXTRACTION_PROMPT_STATIC_PREFIX_ENABLED` | true | 静态前缀（prefix cache 优化） |

### 2.7 v3 抽取（EXTRACTION_V3_*）

v3 抽取以五维向量为底座，双线路 LLM 抽取，关键参数：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `EXTRACTION_V3_LLM_MAX_CONCURRENCY` | 24 | v3 LLM 总并发（匹配 vLLM max-num-seqs） |
| `EXTRACTION_V3_EXTRACTION_ENGINE` | BaseExtract | 抽取引擎（BaseExtract / LangExtract） |
| `EXTRACTION_V3_EXTRACTION_FALLBACK_TO_GLMOCR` | true | LangExtract 失败降级 |
| `EXTRACTION_V3_CATEGORY_CONFIDENCE_THRESHOLD` | 0.35 | 类别置信度阈值 |
| `EXTRACTION_V3_RETRIEVAL_TOP_K` | 20 | 检索融合 top_k |
| `EXTRACTION_V3_RETRIEVAL_RERANK_ENABLED` | true | 重排开关 |
| `EXTRACTION_V3_HYBRID_SEARCH_WEIGHTS` | path:0.15,...:0.15 | 五维检索权重 |

### 2.8 安全策略

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `SECRET_KEY` | change_me... | JWT 签名密钥（≥32 字符，必须替换） |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | 1440 | access token 过期 |
| `REFRESH_TOKEN_EXPIRE_DAYS` | 7 | refresh token 过期 |
| `PASSWORD_MIN_LENGTH` | 8 | 密码最小长度 |
| `LOGIN_MAX_FAILURES` | 5 | 登录失败锁定阈值 |
| `LOGIN_LOCK_MINUTES` | 30 | 锁定时长 |
| `PASSWORD_HISTORY_SIZE` | 5 | 禁用最近 N 个旧密码 |
| `AUDIT_LOG_RETENTION_DAYS` | 90 | 审计日志保留 |

### 2.9 公开接口

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PUBLIC_KB_ID` | None | 公开一体化接口默认 KB ID |

---

## 3. 抽取配置中心

抽取配置中心（`app/services/extraction_config/`）是结构化抽取的核心，提供 KB 级可配置的抽取能力。

### 3.1 模块组成

| 文件 | 职责 |
|------|------|
| `defaults.py` | 全局默认配置（DEFAULT_EXTRACTION_CONFIG） |
| `config_validator.py` | 配置完整性校验（ensure_extraction_config_valid） |
| `resolver.py` | 配置解析（三层覆盖合并） |
| `snapshot_io.py` | 配置快照 IO（版本化） |

### 3.2 默认配置结构

`DEFAULT_EXTRACTION_CONFIG` 包含三个区块：

```python
{
  "retrieval": {           # 检索通用
    "top_k": 20,
    "per_dim_top_k": 30,
    "weights": {"path":0.15,"title":0.20,"content":0.45,"type":0.05,"structural":0.15},
    "default_confidence_threshold": 0.35,
    "reranker": {"enabled": True, "top_n": 15},
    "hybrid": {"enabled": True, "rrf_k": 60, "dense_weight":1.0, "keyword_weight":1.2},
    "query_embed": {...}
  },
  "llm": {                 # 抽取模型（按引擎分组）
    "engine": "BaseExtract",
    "engines": {"BaseExtract": {...}, "LangExtract": {...}}
  },
  "kb_tool": {             # 脚本工具性能参数
    "embed_batch_size": 32, "script_timeout": 10, ...
  }
}
```

### 3.3 配置校验

提交抽取任务前执行全量显式配置校验（`ensure_extraction_config_valid`）：

- Schema 模板完备
- Prompt 模板完备
- 术语集配置（参与检索的 Query 术语集必须配置 `query_main_limit` / `query_refined_limit`）
- LLM 端点可达
- 任一配置项缺失或无效即报错，**不静默回退**，必须全部通过才能提交

### 3.4 引擎切换

| 引擎 | 配置值 | 特点 |
|------|--------|------|
| BaseExtract | `BaseExtract` | 短/长文本分流 + 分批串行，稳定性优先 |
| LangExtract | `LangExtract` | output_schema 强约束 + 类别内并发，质量优先 |

通过 `llm.engine` 切换，LangExtract 失败可降级到 BaseExtract。

---

## 4. 领域模板

内置 4 个领域模板（`app/domain_templates/`），新建知识库时可应用：

| 模板 | 文件 | 适用领域 |
|------|------|----------|
| 材料检测 | `material_testing.py` | 航空航天材料检测标准（默认） |
| 医疗器械 | `medical_device.py` | 医疗器械标准 |
| 合同 | `contract.py` | 合同文档 |
| 通用问答 | `general_qa.py` | 通用 RAG 问答 |

模板定义该领域的类别 Schema、Prompt、术语集默认配置。`base.py` 提供基类，`__init__.py` 注册模板。

应用模板：`POST /kbs/{kb_id}/apply-template`，查询模板：`GET /kbs/templates`。

---

## 5. Hook 机制

Hook 机制（`app/kb_hooks/`）允许每个 KB 自定义抽取流程的关键环节，用可编辑脚本替代硬编码逻辑。

### 5.1 标准接口

| 接口 | 职责 |
|------|------|
| `extract_candidates` | 从文本抽取候选实体 |
| `build_category_schema` | 构建类别 Schema |
| `validate_record` | 校验单条记录 |
| `post_process` | 后处理（归一化/去重等） |
| `category_match` | 类别匹配 |
| `build_doc_info_prompt` | 构建文档信息 Prompt |

### 5.2 Hook 管理

- 脚本位置：`kb_hooks/{kb_id}/hooks.py`
- 管理 API：
  - `GET /kbs/{kb_id}/hook` — 读取 Hook
  - `PUT /kbs/{kb_id}/hook/content` — 更新 Hook 内容
  - `POST /kbs/{kb_id}/hook/reload` — 重载 Hook
- `base.py` 定义基类，`default_hook.py` 提供默认实现，`registry.py` 注册管理

> 设计原则：用脚本执行顺序控制处理流程，替代内置工具；后处理与校验规则集成为可配置项，提升透明度与灵活性。

---

## 6. 数据库迁移

使用 Alembic 管理数据库 schema：

```bash
cd backend
source venv/bin/activate

# 应用所有迁移
alembic upgrade head

# 查看当前版本
alembic current

# 生成新迁移（修改 models 后）
alembic revision --autogenerate -m "描述变更"

# 回滚一个版本
alembic downgrade -1
```

### 现有迁移

| 版本 | 文件 | 内容 |
|------|------|------|
| 001 | `001_initial.py` | 初始 schema（用户/KB/文档/任务/术语/配置等） |
| 002 | `002_add_process_status.py` | 新增 `Document.process_status` 与 `process_task_id`（一体化流程状态） |

---

## 7. 日志与监控

### 7.1 结构化日志

- **structlog**：结构化 JSON 日志，含 `trace_id`、`kb_id`、`document_id` 等上下文字段
- **日志位置**：`backend/logs/`（gitignore 排除）
- **链路追踪**：每个请求注入 `X-Trace-Id`，全链路关联

### 7.2 Prometheus 指标

- **端点**：`GET /metrics`（由 `ENABLE_METRICS` 控制启用）
- **指标**：HTTP 请求量 / 延迟 / 进行中请求数（`fastapi_inprogress`）
- **抓取**：配置 Prometheus 抓取 `http://localhost:8000/metrics`

### 7.3 健康检查

| 端点 | 说明 |
|------|------|
| `GET /health` | 简单健康检查 |
| `GET /api/v1/system/health` | 系统健康 |
| `GET /api/v1/system/health/deep` | 深度健康（含依赖检查） |
| `GET /api/v1/system/health/models` | 模型服务健康 |
| `GET /api/v1/system/health/storage` | 存储健康 |

---

## 8. 日常运维

### 8.1 服务管理

```bash
# 后端 API
cd backend && source venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000

# arq worker
cd backend && ./start_worker.sh

# 前端
cd frontend && pnpm dev

# vLLM 服务（3 个）
cd /home/hanson/doc_parse_project && source venv_model/bin/activate
vllm serve ./models/glm-ocr --port 9977 --served-model-name GLM-OCR ...
vllm serve ./models/Qwen/Qwen3.6-35B-A3B-FP8 --port 9988 --served-model-name Qwem3.6-35B-A3B-FP8 ...
vllm serve ./models/MinerU-Popo --port 9999 --served-model-name Popo ...
```

### 8.2 任务队列管理

```bash
# 查看 arq 队列（Redis db1）
redis-cli -n 1 keys "arq:*"

# 清空遗留任务（谨慎）
redis-cli -n 1 flushdb

# 清理数据库中非终态任务（需按实际 SQL）
```

### 8.3 数据清理

```bash
# 系统清理接口（含预演）
POST /api/v1/system/cleanup/dry-run   # 预演
POST /api/v1/system/cleanup           # 执行清理

# 清理 OCR 临时输出
rm -rf backend/data/ocr_data/{task_id}/
```

### 8.4 知识库备份

```bash
# 创建备份
POST /kbs/{kb_id}/backups

# 下载备份
GET /kbs/{kb_id}/backups/{backup_id}/download

# 恢复
POST /kbs/{kb_id}/backups/restore
```

### 8.5 BM25 模型维护

- KB 级 BM25 模型存储于 `backend/data/bm25/{kb_id_hex}.json`
- 重建流程会自动确保模型存在（缺失则用文档块语料拟合）
- 删除 KB 时同步清理对应 BM25 模型文件

---

## 9. 关键约束与最佳实践

### 9.1 配置约束

- **无静默回退**：任一配置项缺失或无效即报错，仅返回当前引擎自有配置，缺失返回 None
- **全量校验**：提交任务前执行全量显式配置校验
- **术语集必填项**：参与检索（in_query=true）的 Query 术语集必须配置 `query_main_limit` / `query_refined_limit`
- **vLLM 模型名一致**：`--served-model-name` 必须与 `.env` 中对应 `*_MODEL` 完全一致（大小写敏感）

### 9.2 并发约束

- vLLM `--max-num-seqs` 必须 ≥ 应用层总并发
- LangExtract 线路：`inflight = cross_category × within_category`
- BaseExtract 线路：`inflight = cross_category`（类别内串行）
- 超出 vLLM `max-num-seqs` 会排队，影响延迟

### 9.3 隔离约束

- 文档严格归属单一 KB，不跨 KB 共享
- 公开接口凭 task_id 主键查询临时关闭 RLS（安全性由雪花 ID + 限流保证）
- arq 必须正常启用，Redis 连接失败时提交任务即抛错（不静默失败）

### 9.4 UI 约束

- 所有确认框/提示框使用 reka-ui Dialog 自定义对话框，禁用浏览器原生对话框
- reka-ui SelectItem 的 value 不允许空字符串（内部映射为占位符 `__EMPTY__`）

### 9.5 术语规范

- 统一使用"术语集"，不使用"数据集"（已删除 datasets 相关模型）

### 9.6 重排功能

- 当前系统支持重排（`reranker.enabled` 可配置），按需开关
- 重排不可用时应在前端显式提示降级，不静默回退
