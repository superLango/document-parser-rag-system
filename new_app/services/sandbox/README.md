# Sandbox 服务

M4 沙箱服务：按执行契约隔离运行配方/模板代码，校验产物后写入对象存储。

---

## 1. 职责

- 接收编排的 `ExecutionRequest`（OCR 引用、配方/模板 digest、资源限制）。
- 准备工作区：拉取 OCR 产物、校验 sha256、加载并校验配方包与模板。
- 在一次性隔离容器中执行引擎：Docker 执行器（Compose/开发）或 Kubernetes Job 执行器（K8s）。
- 校验产物 schema/sha256/文件白名单/大小，上传到 MinIO/S3。
- 返回 `ExecutionResult`；超时、OOM、非零退出、非法产物有稳定错误码。

不做：OCR、配方匹配、Agent、反馈/晋升、前端。

---

## 2. 目录

```text
services/sandbox/
├── api.py                 # /internal/sandbox/execute、/runtime
├── config.py              # SANDBOX_* 配置
├── docker_executor.py     # Docker Engine API（unix socket）
├── k8s_executor.py        # Kubernetes Job/Pod/ConfigMap API
├── executor.py            # Executor 协议、RawExecution、工厂
├── service.py             # 执行编排、状态分类、产物上传
├── validation.py          # 产物 schema/sha256/跨文件一致性
├── workspace.py           # 工作区、配方/模板解析与 digest 校验
├── runtime/
│   ├── Dockerfile         # 引擎运行时镜像
│   ├── runner.py          # 入口：内置解析或 entrypoint
│   ├── builtin.py         # 确定性表格解析器
│   └── prepare.py         # K8s init 容器：展开 ConfigMap 工作区
└── README.md
```

执行契约：[packages/contracts/src/hanson_contracts/sandbox.py](../../packages/contracts/src/hanson_contracts/sandbox.py)。

---

## 3. API

### POST `/internal/sandbox/execute`

请求（节选）：

```json
{
  "schema_version": "1.0",
  "trace_id": "trace-1",
  "run_id": "run-1",
  "document": {"document_id": "doc-1", "filename": "a.md", "sha256": "..."},
  "ocr": {"storage_key": "runs/run-1/ocr.json", "sha256": "..."},
  "assignments": [
    {"table_id": "T1", "recipe_id": "mechanical_properties_v1", "version": "1.0.0"}
  ],
  "recipe": {"recipe_id": "mechanical_properties_v1", "version": "1.0.0"},
  "template": {"template_id": "product_full", "version": "1.0.0"},
  "engine": {"api": "sandbox-engine/1", "version": "sandbox-engine/1"},
  "limits": {"cpu": 1.0, "memory_mb": 512, "pids": 128, "timeout_seconds": 120, "tmpfs_mb": 64}
}
```

- `recipe.digest` / `template.digest` 可选；提供时严格校验。
- `recipe.manifest` / `recipe.files` 可选，仅用于内联配方或带 entrypoint 的测试包。
- `engine.image` 只能为空或等于服务配置的引擎镜像，否则拒绝。

响应状态：

| status | 含义 |
|---|---|
| `succeeded` | 产物通过校验并已上传 |
| `failed` | 非零退出或引擎错误 |
| `timeout` | 超过 `timeout_seconds`（SIGTERM→SIGKILL）或引擎返回 124 |
| `oom` | 容器 OOMKilled |
| `invalid_output` | 产物缺失、schema 错误、digest 不一致、超出大小限制 |
| `rejected` | 请求/配方/模板/输入校验失败，未进入执行 |

错误码：`SANDBOX_TIMEOUT`、`SANDBOX_OOM`、`SANDBOX_EXIT_NONZERO`、`SANDBOX_INVALID_OUTPUT`、`SANDBOX_OUTPUT_DIGEST_MISMATCH`、`SANDBOX_RECIPE_NOT_FOUND`、`SANDBOX_RECIPE_DIGEST_MISMATCH`、`SANDBOX_TEMPLATE_*`、`SANDBOX_INPUT_TOO_LARGE`、`SANDBOX_RUNTIME_UNAVAILABLE`、`SANDBOX_RBAC_DENIED`、`SANDBOX_UNAVAILABLE`。

### GET `/internal/sandbox/runtime`

返回执行器、运行时、引擎镜像 digest、是否可用与隔离参数，用于运维自检。

---

## 4. 工作区与挂载

```text
/work/input/request.json   只读
/work/input/ocr.json       只读
/work/input/document.json  只读
/work/recipes/<id>/...     只读
/work/templates/<id>/...   只读
/work/output/              可写（产物）
/tmp/                      tmpfs（Docker）/ emptyDir（K8s）
```

运行时镜像内建立 `/input`、`/recipes`、`/templates`、`/output` 到 `/work/*` 的符号链接，配方代码可按文档路径访问。

- **Docker 执行器**：为每次执行创建独立 Docker volume，通过 `PUT /containers/{id}/archive` 写入工作区，执行后 `GET .../archive` 读取 `/work/output`，随后删除容器与 volume。不使用宿主路径 bind mount，避免 Docker-outside-of-Docker 路径耦合。
- **K8s 执行器**：每次执行创建 ConfigMap（工作区 envelope，≤800 KB）与 Job；init 容器 `prepare.py` 展开到 emptyDir，主容器输出 base64 envelope 到 stdout，服务读取 Pod 日志后校验。输出上限 8 MB。

---

## 5. 隔离配置

| 维度 | Docker | Kubernetes |
|---|---|---|
| 网络 | `--network none` | deny-all NetworkPolicy（需 Calico/Cilium） |
| rootfs | `ReadonlyRootfs=true` | `readOnlyRootFilesystem=true` |
| 用户 | `65534:65534` | `runAsUser/runAsGroup=65534`、`runAsNonRoot` |
| capability | `CapDrop=ALL` | `capabilities.drop=ALL` |
| 提权 | `no-new-privileges` | `allowPrivilegeEscalation=false` |
| seccomp | Docker default | `RuntimeDefault` |
| 资源 | memory/swap/cpu/pids/tmpfs | Pod `resources.limits`、emptyDir sizeLimit |
| 超时 | 2 s 轮询，SIGTERM→宽限→SIGKILL | `activeDeadlineSeconds` |
| 服务账号 | 不注入 | `automountServiceAccountToken=false` |

说明：

- Docker 执行器需要把宿主 `/var/run/docker.sock` 挂给**沙箱服务容器**；执行容器本身不挂载 socket。
- K8s 执行器需要 `sandbox` ServiceAccount + Role（Job/Pod/Log/ConfigMap），见 [sandbox.yaml](../../deploy/k8s/base/sandbox.yaml)。
- 主 kind 集群的 kindnet 不执行 NetworkPolicy；策略实测使用临时 Calico 集群，见 [M4 运行时评分报告](../../docs/reports/M4-runtime-evaluation.md)。

---

## 6. 引擎运行时镜像

```bash
docker build -f services/sandbox/runtime/Dockerfile -t hanson-sandbox-runtime:local .
```

- `python:3.12-slim`，`USER 65534`，`/engine` 只读。
- 入口：`python -B /engine/runner.py`。
- 无代码配方：`builtin.py` 按配方 `bindings`（row_key/conditions/measures）解析 `TableGrid`，输出 records/evidence/diagnostics。
- 带 `entrypoint` 的配方：在沙箱内以子进程执行 `entry.py`，读取 `HANSON_REQUEST`/`HANSON_OUTPUT_DIR`，必须写 `result.json`、`records.json`、`evidence.jsonl`、`diagnostics.json`；runner 统一补 `metrics.json`/`manifest.json`。
- 产物：`result.json`、`records.json`、`evidence.jsonl`、`diagnostics.json`、`metrics.json`、`manifest.json`。

---

## 7. 配置（SANDBOX_ 前缀）

| 变量 | 默认 | 说明 |
|---|---|---|
| `SANDBOX_EXECUTOR` | `docker` | `docker` / `kubernetes` |
| `SANDBOX_RUNTIME` | `runc` | Docker runtime（gVisor 注册后可为 `runsc`） |
| `SANDBOX_ENGINE_IMAGE` | `hanson-sandbox-runtime:local` | 引擎镜像 |
| `SANDBOX_DOCKER_SOCKET` | `/var/run/docker.sock` | Docker Engine socket |
| `SANDBOX_WORKSPACE_ROOT` | `/tmp/hanson-sandbox` | 临时工作区根目录 |
| `SANDBOX_MAX_INPUT_BYTES` | 64 MiB | OCR 输入上限 |
| `SANDBOX_MAX_OUTPUT_BYTES` | 16 MiB | 产物总大小上限 |
| `SANDBOX_DEFAULT_CPU/MEMORY_MB/PIDS/TIMEOUT_SECONDS/TMPFS_MB` | 1.0/512/128/120/64 | 默认限制（请求可覆盖） |
| `SANDBOX_KUBERNETES_NAMESPACE` | `hanson-standard` | Job 命名空间 |
| `SANDBOX_KUBERNETES_WORKSPACE_MB` | 256 | emptyDir 限制 |
| `OBJECT_STORAGE_*` | 与全局一致 | MinIO/S3 |

---

## 8. 启动与验证

```bash
# Compose
cd deploy/compose
docker compose up -d sandbox orchestration

# 运行时自检
curl -s http://localhost:18004/internal/sandbox/runtime | python -m json.tool

# 直接执行 smoke（在沙箱容器内，使用 MinIO）
docker exec -i hanson-new-app-sandbox-1 python - < scripts/dev/sandbox-check.py

# Compose 全链路
bash scripts/dev/e2e-check.sh <document_id>

# K8s
bash scripts/dev/k8s-deploy.sh
bash scripts/dev/k8s-e2e.sh tests/fixtures/mechanical.md
```

测试：

```bash
python -m pytest tests/integration/sandbox -q
# Docker 执行器测试（Linux / 挂载 docker.sock 的容器）
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$PWD":/app -w /app \
  -e PYTHONPATH=/app:/app/packages/contracts/src \
  hanson-new-app:local python -m pytest tests/integration/sandbox/test_docker_executor.py -q
```

---

## 9. 已知限制

1. **K8s 工作区上限 800 KB**：Job 执行器用 ConfigMap 传递输入；大 OCR 需后续改为 PVC/对象存储挂载。
2. **K8s 输出上限 8 MB**：输出以 base64 envelope 经 stdout 回传；大产物需改为共享存储。
3. **NetworkPolicy 依赖 CNI**：kind 默认 kindnet 不执行策略；生产需 Calico/Cilium。
4. **gVisor 未注册到 Docker Desktop**：当前用 `runsc do` 验证；节点注册后通过 `SANDBOX_RUNTIME=runsc` 切换。
5. **Kata 未验证**：本机无 kata-runtime/QEMU，静态包 1.02 GB 下载超时；生产多租户再评估。
6. **配方代码信任边界**：内置解析器与 entrypoint 均在同一隔离容器内运行；entrypoint 包的文件目前随注册中心包信任，后续可加入代码签名。

---

## 10. 回滚

- 编排：`SANDBOX_USE_FAKE=true` 回到 M1 fake 沙箱。
- 服务：停止 sandbox 容器/Deployment；编排重试后进入失败态，不影响 OCR/路由。
- 运行时：`SANDBOX_RUNTIME=runc` 为默认；切换 gVisor 只改配置，不改契约。
