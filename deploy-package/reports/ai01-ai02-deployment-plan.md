# AI-01 / AI-02 新服务器部署方案（待确认）

- 调研日期：2026-11-15
- 目标：把新架构部署到 `193.168.2.201`（AI-01）和 `193.168.2.202`（AI-02），新项目对外端口保持老项目的 `18000` / `18080`
- 当前状态：**仅完成只读调研和方案设计，未修改两台服务器**
- 结论：推荐 **201 部署新应用栈，202 只保留 Qwen 模型**；先并行部署到临时端口验证，再停老项目并切到 `18000/18080`

## 1. 调研结论

### 1.1 服务器资源

| 项 | 201 `spark-5a59` | 202 `spark-d629` |
| --- | --- | --- |
| 系统 | Ubuntu 24.04.5 LTS，aarch64 | Ubuntu 24.04.5 LTS，aarch64 |
| CPU | 20 核 | 20 核 |
| 内存 | 121 GiB，已用 54 GiB，可用约 66 GiB | 121 GiB，已用 93 GiB，可用约 28 GiB |
| GPU | NVIDIA GB10 | NVIDIA GB10 |
| 磁盘 | 3.7 T，已用 101 G | 3.7 T，已用 139 G |
| Docker | 29.2.1，当前用户可用 | 29.2.1，**当前用户无 docker 组权限**，`sudo` 需要密码 |

### 1.2 201 当前运行内容

| 内容 | 端口/路径 | 说明 |
| --- | --- | --- |
| 老项目 platform-api | `18000` | `/health` 200，`/docs` 200 |
| 老项目 web | `18080` | 老前端，`/` 200 |
| 老项目 postgres | 容器内 5432 | 卷 `hanson-doc-parse_postgres-data`，当前 13 份文档 |
| 老项目 engine/worker/selfheal | 容器内 | 6 个主容器 + 2 个 selfheal 容器 |
| GLM-OCR | `9977` | vLLM，模型名 `GLM-OCR`，max_model_len 32768，max-num-seqs 16，GPU util 0.30 |
| 版面分析 | `9979` | PP-DocLayoutV3，`/health` 200，`/v1/layout` 可用 |
| 其他 | `8088`、`8010`、`8100` | file_parse、老 engine-api、selfheal |

老项目 compose 路径：

```text
/home/htjiance8/Desktop/AI-01/hanson-doc-parse-4e179cc2/infra/docker/compose.yaml
/home/htjiance8/Desktop/AI-01/hanson-doc-parse-4e179cc2/infra/docker/compose.ai01.yaml
/home/htjiance8/Desktop/AI-01/hanson-doc-parse-4e179cc2/infra/docker/compose.selfheal.ai01.yaml
```

### 1.3 202 当前运行内容

202 只有 Qwen 模型，没有业务容器；Docker 服务在运行，但 `htjiance8` 不在 docker 组。

Qwen 实际启动参数：

```text
模型路径: /home/htjiance8/Desktop/AI-02/hansondoc-deploy-hantang/models/qwen36/Qwen3.6-35B-A3B-NVFP4
模型目录: 25 GB，6 个 safetensors 分片
model_type: qwen3_5_moe
量化: compressed-tensors
端口: 9988
served-model-name: Qwen3.6-35B-A3B-FP8
max_model_len: 262144
max-num-seqs: 20
max-num-batched-tokens: 32768
gpu-memory-utilization: 0.68
kv-cache-dtype: fp8
实际 GPU 占用: 约 76,996 MiB
```

**重要：** 实际服务名是 `Qwen3.6-35B-A3B-FP8`，不是之前配置里的 `Qwen3.6-35B-A3B-NVFP4`。新项目 `AGENT_MODEL` 必须改成 `Qwen3.6-35B-A3B-FP8`。

### 1.4 网络连通性

已实测：

- 201 容器内可访问 `201:9977`、`201:9979`、`202:9988`，均 200
- 202 可访问 `201:9977`、`201:9979`，均 200
- 201 可访问 `202:9988`，200
- 新应用容器使用 `http://193.168.2.201:9977`、`http://193.168.2.201:9979`、`http://193.168.2.202:9988` 即可，不需要 `host.docker.internal`

## 2. 推荐部署拓扑

```text
201 (spark-5a59)                         202 (spark-d629)
├─ 老项目（切换前运行）                  └─ Qwen3.6-35B-A3B-FP8 :9988
│  ├─ platform-api :18000
│  └─ web :18080
├─ GLM-OCR :9977（宿主进程，保留）
├─ PP-DocLayoutV3 :9979（宿主进程，保留）
└─ 新项目应用栈（Docker）
   ├─ api-gateway :18000（切换后）
   ├─ web :18080（切换后）
   ├─ orchestration / ocr / agent / sandbox / review / recipe-registry
   ├─ postgres :15432（仅本机）
   ├─ redis :16379（仅本机）
   └─ minio :19000/19001（仅本机）
```

**不推荐把应用栈部署到 202**：202 只有 28 GiB 可用内存，Qwen 已占 76.9 GiB GPU；应用栈放 201 更稳，202 保持纯模型节点。

## 3. 新项目端口与环境变量

### 3.1 端口

| 用途 | 端口 | 说明 |
| --- | --- | --- |
| 新 API Gateway | `18000` | 保持老项目 API 端口 |
| 新 Web | `18080` | 保持老项目 Web 端口 |
| 新 PostgreSQL | `15432` | 只绑定 127.0.0.1 |
| 新 Redis | `16379` | 只绑定 127.0.0.1 |
| 新 MinIO | `19000/19001` | 只绑定 127.0.0.1 |
| GLM-OCR | `9977` | 复用 201 现有服务 |
| 版面分析 | `9979` | 复用 201 现有服务，注意不是 9978 |
| Qwen | `9988` | 复用 202 现有服务 |

### 3.2 201 新项目 `.env` 关键值

```env
ENVIRONMENT=production

GATEWAY_PORT=18000
WEB_PORT=18080

POSTGRES_PORT=15432
REDIS_PORT=16379
MINIO_PORT=19000
MINIO_CONSOLE_PORT=19001

POSTGRES_PASSWORD=<现场设置>
MINIO_ROOT_USER=<现场设置>
MINIO_ROOT_PASSWORD=<现场设置>
INTERNAL_API_TOKEN=<现场设置>
API_AUTH_TOKEN=

GLM_OCR_BASE_URL=http://193.168.2.201:9977/v1
GLM_OCR_MODEL=GLM-OCR
LAYOUT_BASE_URL=http://193.168.2.201:9979
AGENT_BASE_URL_PRIMARY=
AGENT_BASE_URL_SECONDARY=
AGENT_BASE_URL_TERTIARY=http://193.168.2.202:9988
AGENT_MODEL=Qwen3.6-35B-A3B-FP8
AGENT_CONTEXT_WINDOW=65536
AGENT_MAX_OUTPUT_TOKENS=4096

PARSER_ASSET_REQUIRED=true
HUMAN_REVIEW_REQUIRED=true
OCR_LAYOUT_FIRST=true
LAYOUT_BLOCK_CONCURRENCY=2
LAYOUT_PAGE_CONCURRENCY=2
GLM_OCR_MAX_TOKENS=8192

HANSON_NETWORK_SUBNET=10.88.0.0/16
```

说明：

- `AGENT_BASE_URL_PRIMARY/SECONDARY` 置空，避免启动探测旧的 `39.107.239.208:35035`、`192.168.1.35:9991`。
- 老项目 GLM 当前 `max-num-seqs=16`，新项目并发先降到 `2/2`，和老项目共用期间避免打满；老项目停掉后可恢复 `4/4`。
- `LAYOUT_BASE_URL` 必须用 `9979`，不是 9978；健康检查路径是 `/health`，不是 `/healthz`。
- Qwen 的 `262144` 是最大上下文，不是单次输出；新项目当前 `AGENT_MAX_OUTPUT_TOKENS=4096`，如需更长输出再调大。

## 4. 关键风险与前置条件

### 4.1 镜像架构不匹配（必须先解决）

当前本地打出的 3 个自建镜像是 **linux/amd64**：

```text
hanson-new-app:local          linux/amd64
hanson-web:local              linux/amd64
hanson-sandbox-runtime:local  linux/amd64
```

201/202 是 **aarch64**。直接把现有 amd64 镜像 `docker load` 到服务器上会报 `exec format error`，不能运行。

推荐做法：

- 在 201 上使用源码原生构建 arm64 镜像（Docker 已可用，aarch64 原生编译最稳）：
  ```bash
  docker build -f deploy/compose/Dockerfile -t hanson-new-app:local .
  docker build -f deploy/compose/web.Dockerfile -t hanson-web:local .
  docker build -f services/sandbox/runtime/Dockerfile -t hanson-sandbox-runtime:local .
  ```
- 或在本地用 buildx + QEMU 构建 `linux/arm64`，但需要先安装 arm64 binfmt；构建成功后再上传镜像。
- `postgres:16-alpine`、`redis:7-alpine`、`minio/minio:latest` 在 201 上直接 `docker pull` 即可自动拉 arm64 版本。

### 4.2 端口切换

老项目 `18000/18080` 正在使用，新项目不能同时占用。采用“先临时端口并行、后切换”的方式：

1. 新项目先用 `18001/18081` 启动并验证，不影响老项目。
2. 验收通过后停老项目，保留其数据卷。
3. 新项目改回 `18000/18080`，重启 gateway/web。

### 4.3 老项目数据

老项目当前 13 份文档，主要在 `hanson-doc-parse_platform-data` 的 `/data/platform/uploads/` 下，状态大多为 `queued`，另有 1 份 `review`。新项目数据库结构不同，**不能直接复用老库**。

可选策略：

- **A（推荐）**：新库从空开始，按需把老项目 13 份 PDF 重新上传到新系统；不迁移老的结构化结果。
- **B**：只迁移原始 PDF，重新解析，保留老项目作为只读归档。
- **C**：需要保留老项目的审核结果/字段级数据，则另做导出与字段映射，不纳入本次首次部署。

### 4.4 健康检查路径兼容

老项目 API 是 `/health`，新项目是 `/healthz`。如果现场监控或外部系统调用 `/health`，建议在新网关增加 `/health` 兼容别名（返回与 `/healthz` 相同），避免切换后监控误报。

### 4.5 模型服务不要重启

本次部署不需要改 GLM-OCR、版面服务、Qwen 的启动参数；新项目只作为客户端调用。尤其是 202 的 Qwen 当前占用 76.9 GiB，重启会影响现有业务。模型重启脚本另做站点化适配后再使用（现有部署包里的模型脚本路径是旧模型服务器 `192.168.1.35` 的，不能直接用于 201/202）。

## 5. 部署步骤

### 阶段 0：准备与备份（不改老项目）

1. 备份老项目数据卷：
   ```bash
   mkdir -p /home/htjiance8/backup/20261115
   docker run --rm -v hanson-doc-parse_postgres-data:/data \
     -v /home/htjiance8/backup/20261115:/backup alpine \
     tar czf /backup/old-postgres-data.tar.gz -C /data .
   docker run --rm -v hanson-doc-parse_platform-data:/data \
     -v /home/htjiance8/backup/20261115:/backup alpine \
     tar czf /backup/old-platform-data.tar.gz -C /data .
   ```
2. 记录老项目当前状态：`docker compose ps`、`curl 18000/health`、`curl 18080/`。
3. 检查 201 的 `15432/16379/19000/19001/18001/18081` 均空闲。
4. 记录 201/202 模型端点基线：`9977`、`9979`、`202:9988`。

### 阶段 1：201 上构建 arm64 镜像

1. 把 `new_app` 源码和部署包（不含 amd64 images）上传到 201：
   ```text
   /home/htjiance8/Desktop/AI-01/hanson-doc-parse-new/
   ```
2. 在 201 上原生构建 3 个镜像。
3. 校验：
   ```bash
   docker image inspect hanson-new-app:local --format '{{.Os}}/{{.Architecture}}'
   # 期望 linux/arm64
   ```
4. 拉取 arm64 基础镜像：`postgres:16-alpine`、`redis:7-alpine`、`minio/minio:latest`。

### 阶段 2：临时端口并行部署

1. 复制 `.env.example` 为 `.env`，按第 3.2 节填值，端口改为 `18001/18081`。
2. 启动新栈：
   ```bash
   bash scripts/start.sh
   bash scripts/status.sh
   bash scripts/smoke-test.sh
   ```
3. 验证：
   - `http://193.168.2.201:18001/healthz`
   - `http://193.168.2.201:18081/`
   - 上传一份 PDF，确认 OCR 后端为 `layout_first`，结果正常
   - 确认 201 老项目 `18000/18080` 未受影响
4. 页面验证：`http://193.168.2.201:18081/integration/task/{task_id}`

### 阶段 3：停老项目并切换端口

1. 通知维护窗口，停止老项目（保留数据卷）：
   ```bash
   cd /home/htjiance8/Desktop/AI-01/hanson-doc-parse-4e179cc2
   docker compose -p hanson-doc-parse \
     -f infra/docker/compose.yaml \
     -f infra/docker/compose.ai01.yaml down
   docker compose -p hanson-doc-parse-selfheal \
     -f infra/docker/compose.selfheal.ai01.yaml down
   ```
2. 确认 `18000/18080` 释放。
3. 修改新项目 `.env`：
   ```env
   GATEWAY_PORT=18000
   WEB_PORT=18080
   ```
4. 只重建网关与 Web：
   ```bash
   docker compose --project-name hanson-deploy --env-file .env -f docker-compose.yml \
     up -d --no-deps --force-recreate api-gateway web
   ```
5. 验证新地址：
   - `http://193.168.2.201:18000/healthz`
   - `http://193.168.2.201:18080/`
   - `http://193.168.2.201:18080/api/v1/integration/...`（旧对接路径）
6. 建议增加 `/health` 兼容别名后重新验证。

### 阶段 4：数据迁移（可选，按确认结果）

1. 从老项目 `platform-data` 卷复制 13 份 PDF 到宿主机。
2. 通过新项目 `/api/v1/integration/upload` 或前端上传，逐份重新解析。
3. 不迁移老库的结构化结果；如需保留，单独做导出映射。
4. 迁移后核对文档数量、解析状态和结果抽样。

### 阶段 5：验收与回滚

验收：

- 3 个模型端点全 200
- 新栈全部容器 healthy
- 22 页样本解析成功，`backend=layout_first`
- 集成四接口正常
- 新页面原文 PDF 与结果正常
- `18000/18080` 外部访问正常
- 老项目数据卷、模型进程均未受影响

回滚：

```bash
# 停新栈
docker compose --project-name hanson-deploy --env-file .env -f docker-compose.yml down

# 启动老项目
cd /home/htjiance8/Desktop/AI-01/hanson-doc-parse-4e179cc2
docker compose -p hanson-doc-parse \
  -f infra/docker/compose.yaml \
  -f infra/docker/compose.ai01.yaml up -d
docker compose -p hanson-doc-parse-selfheal \
  -f infra/docker/compose.selfheal.ai01.yaml up -d
```

## 6. 需要你确认的事项

1. **是否同意“201 应用栈 + 202 纯 Qwen”拓扑？** 不把应用部署到 202。
2. **是否同意先并行部署到 `18001/18081`，验收后再停老项目切到 `18000/18080`？**
3. **老项目 13 份文档是否迁移到新库？** 建议只迁移原始 PDF 并重新解析，不迁移老结构化结果。
4. **arm64 镜像采用哪种方式构建？** 推荐直接在 201 原生构建；本地交叉构建作为备选。
5. **是否增加 `/health` 兼容别名**，避免老监控在切换后失效。
6. **维护窗口**：停老项目到新项目 18000/18080 验证完成期间，老系统不可用。
