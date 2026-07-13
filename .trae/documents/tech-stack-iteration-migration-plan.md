# 技术栈迭代迁移执行计划

## 概述

对已完成代码进行5项技术栈迭代迁移，按依赖顺序分4个批次执行。每批次完成后运行全量测试确保不破坏现有功能（当前基线：292个测试通过）。

## 当前状态分析

### Celery 集成点（共11个文件）
- `backend/app/tasks/celery_app.py` — Celery应用实例（broker/backend/beat配置）
- `backend/app/tasks/document_tasks.py` — `@celery_app.task(bind=True, name="parse_document")`，内部用`asyncio.run()`调用异步服务，`self.update_state()`上报进度
- `backend/app/tasks/rag_tasks.py` — `@celery_app.task(bind=True, name="rag.index_document/rebuild_index/remove_document")`
- `backend/app/tasks/graph_tasks.py` — `@celery_app.task(bind=True, name="graph.build_document/rebuild_all/remove_document")`
- `backend/app/api/v1/endpoints/tasks.py` — `parse_document.delay()`提交任务，`AsyncResult(task_id, app=celery_app)`查询状态+SSE轮询
- `backend/app/api/v1/endpoints/knowledge_base.py` — `index_document.delay()` / `rebuild_index.delay()` / `remove_document.delay()`
- `backend/app/api/v1/endpoints/knowledge_graph.py` — `build_document_graph.delay()`等3个delay调用
- `backend/app/core/config.py` — `CELERY_BROKER_URL` + `CELERY_RESULT_BACKEND`

### Redis/MinIO 集成点
- `deploy/docker-compose.yml` — Redis 7-alpine (L28-40) + MinIO (L42-58)，Milvus依赖`MINIO_ADDRESS: minio:9000` (L105)
- `deploy/redis.conf` — 10行Redis配置
- `backend/app/services/storage_service.py` — Minio SDK客户端，`asyncio.to_thread`包装同步操作（upload/download/delete/get_presigned_url）
- `backend/app/core/config.py` — `REDIS_URL` + `MINIO_ENDPOINT/ACCESS_KEY/SECRET_KEY/BUCKET/SECURE` (L60-76)
- `backend/.env.example` — Redis/MinIO配置项 (L14-22, L54-55)

### DeepKE 集成点
- `backend/app/services/graph_extract_service.py` — `_init_model()`尝试`from deepke import DeepKE`(L119-143)，失败回退到LLM抽取
- `backend/tests/test_graph_extract_service.py` — 29个测试，包含DeepKE回退测试

### MinerU 集成点
- `backend/app/services/layout_service.py` — 双引擎（MinerU主 + PP-DocLayoutV2备），L56-80标签映射

---

## 执行计划

### Batch 1: 基础设施迁移（Valkey + SeaweedFS）

#### Task 1.1: Redis → Valkey
**文件**: `deploy/docker-compose.yml`, `deploy/redis.conf` → `deploy/valkey.conf`

**docker-compose.yml 修改**:
```yaml
# L27-40: redis → valkey
valkey:
  image: valkey/valkey:8-alpine
  container_name: docparser-valkey
  ports:
    - "6379:6379"
  volumes:
    - valkey_data:/data
    - ./valkey.conf:/usr/local/etc/valkey/valkey.conf
  command: valkey-server /usr/local/etc/valkey/valkey.conf
  healthcheck:
    test: ["CMD", "valkey-cli", "ping"]
    interval: 10s
    timeout: 5s
    retries: 5
```

- `deploy/redis.conf` 重命名为 `deploy/valkey.conf`（内容不变，Valkey兼容Redis配置格式）
- `volumes` 部分 `redis_data` → `valkey_data`
- config.py 中 `REDIS_URL` 保持不变（`redis://localhost:6379/0`，Valkey兼容Redis协议）

#### Task 1.2: MinIO → SeaweedFS
**文件**: `deploy/docker-compose.yml`, `backend/app/services/storage_service.py`, `backend/app/core/config.py`, `backend/.env.example`

**docker-compose.yml 修改**:
```yaml
# L42-58: minio → seaweedfs
seaweedfs:
  image: chrislusf/seaweedfs:latest
  container_name: docparser-seaweedfs
  command: server -s3 -s3.config=/etc/seaweedfs/s3.json
  ports:
    - "9000:8333"   # S3 API
    - "9001:8888"   # Web UI
  environment:
    S3_CONFIG: /etc/seaweedfs/s3.json
  volumes:
    - seaweedfs_data:/data
    - ./seaweedfs_s3.json:/etc/seaweedfs/s3.json
```

**新建** `deploy/seaweedfs_s3.json`:
```json
{
  "identities": [
    {
      "name": "admin",
      "credentials": [
        {"accessKey": "minioadmin", "secretKey": "change_me_minio"}
      ],
      "actions": ["Admin", "Read", "Write", "List", "Tagging"]
    }
  ]
}
```

**Milvus 配置修改** (docker-compose.yml L105):
```yaml
MINIO_ADDRESS: seaweedfs:8333
```

**storage_service.py 重写**: Minio SDK → boto3 S3兼容客户端
- 移除 `from minio import Minio` 和 `from minio.error import S3Error`
- 新增 `import boto3` 和 `from botocore.config import Config`
- `_get_client()` 使用 `boto3.client("s3", endpoint_url=..., aws_access_key_id=..., aws_secret_access_key=...)`
- `upload()`: `client.put_object(Bucket=..., Key=..., Body=data, ContentType=...)`
- `download()`: `client.get_object(Bucket=..., Key=...)` → `response["Body"].read()`
- `delete()`: `client.delete_object(Bucket=..., Key=...)`
- `get_presigned_url()`: `client.generate_presigned_url("get_object", Params={...}, ExpiresIn=...)`
- 保持接口签名完全不变（upload/download/delete/get_presigned_url参数和返回值一致）
- boto3是同步SDK，保留 `asyncio.to_thread` 包装

**config.py 修改**:
```python
# L68-76: MINIO_ 前缀改为 S3_ 兼容命名（但保留旧名以减少改动）
# 保持 MINIO_ENDPOINT/MINIO_ACCESS_KEY 等字段名不变（作为S3兼容配置）
# 新增 S3_ENDPOINT_URL 用于 boto3
S3_ENDPOINT_URL: str = Field(default="http://localhost:9000", description="S3兼容存储端点URL")
```

**.env.example 修改**:
```env
# S3 Compatible Storage (SeaweedFS)
S3_ENDPOINT_URL=http://localhost:9000
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=change_me_minio
MINIO_BUCKET=documents
MINIO_SECURE=false
```

**验收**: `docker-compose config` 验证配置正确

---

### Batch 2: 任务队列迁移（Celery → arq）

#### Task 2.1: 创建 arq worker 配置
**新建** `backend/app/tasks/arq_worker.py`:
```python
"""arq 异步任务队列 Worker 配置。

替代原 celery_app.py，原生asyncio，与FastAPI完美契合。
"""
from arq import cron_kwargs
from arq.connections import RedisSettings

# 任务函数注册
async def parse_document_task(ctx, document_id: str, schema_id: str = None, term_base_id: str = None):
    """文档解析任务（arq入口）"""
    from app.tasks.document_tasks import _parse_document_impl
    return await _parse_document_impl(document_id, schema_id, term_base_id, ctx)

# ... 其他任务注册

class WorkerSettings:
    redis_settings = RedisSettings(host="localhost", port=6379, database=1)
    functions = [parse_document_task, index_document_task, ...]
    max_jobs = 1  # 等价于 worker_prefetch_multiplier=1
    job_timeout = 3600
    cron_jobs = [
        cron(cleanup_expired_tasks, hour=2, minute=0),
    ]
```

#### Task 2.2: 重写任务文件（3个文件）
**document_tasks.py**:
- 移除 `from celery import Task` 和 `from app.tasks.celery_app import celery_app`
- `@celery_app.task(bind=True, name="parse_document")` → 导出 `async def parse_document_impl()`
- `self.update_state(state="PROGRESS", meta={...})` → 通过arq ctx 或数据库更新进度
- `asyncio.run()` 包装移除（arq任务本身就是async）
- 保留所有业务逻辑不变（下载→OCR→版面→抽取→术语→保存）

**rag_tasks.py**: 同上模式，3个任务
**graph_tasks.py**: 同上模式，3个任务

**进度上报策略**: arq无`self.update_state`，改为直接更新数据库Task记录的progress字段（已有Task模型）。SSE端点改为轮询数据库而非AsyncResult。

#### Task 2.3: 更新API端点任务提交+状态查询（3个文件）
**tasks.py**:
- 移除 `from celery.result import AsyncResult` 和 `from app.tasks.celery_app import celery_app`
- `parse_document.delay(...)` → `await pool.enqueue_job("parse_document_task", document_id, ...)` 
- `AsyncResult(task_id, app=celery_app).state` → 查询数据库Task记录的status字段
- SSE端点: 轮询数据库Task.progress而非AsyncResult.info
- 新增 arq Redis pool 初始化: `from arq import create_pool; pool = await create_pool(RedisSettings(...))`

**knowledge_base.py**: `.delay()` → `enqueue_job()`
**knowledge_graph.py**: `.delay()` → `enqueue_job()`

#### Task 2.4: 更新config.py
- 移除 `CELERY_BROKER_URL` 和 `CELERY_RESULT_BACKEND`
- 新增 `ARQ_REDIS_HOST` / `ARQ_REDIS_PORT` / `ARQ_REDIS_DB`（或复用`REDIS_URL`解析）

**验收**: `arq app.tasks.arq_worker.WorkerSettings` 可启动worker

---

### Batch 3: 知识抽取迁移（DeepKE → OneKE）

#### Task 3.1: 重写 graph_extract_service.py
**文件**: `backend/app/services/graph_extract_service.py`

- 移除 `_init_model()` 中的 `from deepke import DeepKE` 尝试
- 移除 `_extract_with_deepke()` 方法
- 将 `_extract_with_llm()` 重命名为主路径，增强prompt为OneKE指令格式
- OneKE指令格式（基于schema的IEPile格式）:
  ```
  你是一个知识抽取助手。请从以下文本中抽取实体和关系。
  
  Schema:
  实体类型: 材料、标准、工艺、参数、组织、设备、属性值
  关系类型: 执行标准、材质、用于、包含、参数值、属于、生产于
  
  文本: {text}
  
  请输出JSON格式:
  {"entities": [{"text": "...", "type": "..."}], "relations": [{"head": "...", "relation": "...", "tail": "..."}]}
  ```
- 使用 `llm_service.generate_json()` 调用vLLM/Qwen3.5-9B
- 保留Entity/Relation/ExtractionResult数据模型不变
- 保留`extract()` / `extract_batch()` 接口签名不变

#### Task 3.2: 更新测试
**文件**: `backend/tests/test_graph_extract_service.py`
- 移除DeepKE相关测试（TestDeepKEExtraction, TestDeepKEFallback）
- 保留LLM抽取测试（已覆盖主要逻辑）
- 新增OneKE指令格式验证测试

**验收**: 知识抽取服务测试全部通过

---

### Batch 4: MinerU-Popo 增强 + 清理

#### Task 4.1: 集成MinerU-Popo后处理（可选，视模型可用性）
**新建** `backend/app/services/popo_service.py`
- 下载MinerU-Popo模型（4B轻量级）
- 实现: 跨页表格合并、标题层级重建、图文关联
- 在`document_tasks.py`解析管道中集成（OCR/版面后、抽取前）

#### Task 4.2: 清理与验证
- 移除 `deepke-env` Conda环境
- 更新 `backend/requirements.txt`: 移除`celery`/`redis`/`minio`，新增`arq`/`boto3`
- 更新 `backend/.env.example`
- 运行全量测试（目标：292+测试通过）
- 更新 `spec.md` / `tasks.md` / `checklist.md` 勾选已完成项

---

## 并行化策略

```
Batch 1 (基础设施)     Batch 2 (任务队列)     Batch 3 (知识抽取)
┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐
│ 1.1 Valkey      │   │ 2.1 arq worker  │   │ 3.1 OneKE重写   │
│ 1.2 SeaweedFS   │   │ 2.2 重写3个task  │   │ 3.2 更新测试    │
│                 │   │ 2.3 更新3个API   │   │                 │
│                 │   │ 2.4 更新config   │   │                 │
└────────┬────────┘   └────────┬────────┘   └────────┬────────┘
         │                     │                      │
         └──────────┬──────────┘                      │
                    │                                 │
              Batch 4 (清理+MinerU-Popo)              │
              ┌──────────────────────┐                │
              │ 4.1 Popo (可选)      │◄───────────────┘
              │ 4.2 清理+全量测试    │
              └──────────────────────┘
```

- **Batch 1, 2, 3 可完全并行**（互不依赖）
- Batch 2 的`enqueue_job`需要Valkey运行（Batch 1.1），但代码修改可并行
- Batch 4 依赖前3个Batch完成

## 假设与决策

1. **arq进度上报**: arq无Celery的`self.update_state`机制，改用数据库Task记录更新progress字段。SSE端点从轮询AsyncResult改为轮询数据库。
2. **boto3保持asyncio.to_thread**: boto3是同步SDK，与Minio SDK一样需要`asyncio.to_thread`包装。接口签名保持不变。
3. **SeaweedFS S3端口**: SeaweedFS默认S3端口为8333，映射到宿主机9000以保持与MinIO一致。配置中`S3_ENDPOINT_URL`指向`http://localhost:9000`。
4. **OneKE不下载独立模型**: OneKE本质是LLM指令格式，通过现有vLLM/Qwen3.5-9B实现，无需额外模型下载。使用IEPile格式的schema指令prompt。
5. **MinerU-Popo可选**: 如果4B模型下载困难或集成复杂，可作为后续增强，不阻塞主要迁移。
6. **Valkey配置复用**: Valkey 100%兼容Redis协议，`REDIS_URL`连接字符串不变，`valkey.conf`内容与原`redis.conf`一致。
7. **移除deepke-env**: Conda环境不再需要，因为OneKE通过vLLM推理。

## 验证步骤

1. **Batch 1完成后**: `docker-compose config` 验证；`python -c "from app.services.storage_service import storage_service"` 导入成功
2. **Batch 2完成后**: `arq app.tasks.arq_worker.WorkerSettings` 可启动；全量测试通过
3. **Batch 3完成后**: 知识抽取服务测试全部通过
4. **Batch 4完成后**: 全量测试≥292通过；`pip list | grep celery` 无输出；`pip list | grep minio` 无输出
5. **最终**: 更新spec/tasks/checklist文档，勾选所有已完成项
