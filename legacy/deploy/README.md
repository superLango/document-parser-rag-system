# 三平面部署

```text
平台平面（本机）     apps/api + apps/web + apps/worker + 本地 SQLite/MinIO（可选）
引擎平面（本机）     metal-doc-agent（API 同进程，worker 独立）
模型平面（公网穿透） GLM-OCR 35032 / Layout 35033+35034 / vLLM 35035
模型平面（局域网兜底） GLM-OCR 9977 / Layout 9978+9979 / vLLM 9991（192.168.188.75）
```

## 本机启动（无 Docker）

前置：

```powershell
pip install -e "metal-doc-agent[api,yaml,dev]"
pip install -e "apps/api"
pnpm install
```

启动/停止：

```powershell
deploy/start_local.ps1
deploy/start_local.ps1 -NoWeb        # 只起 API + worker
deploy/stop_local.ps1
```

默认地址：`http://127.0.0.1:8765`（API）、`http://127.0.0.1:5173`（Web）。
日志在 `deploy/logs/`，PID 在 `deploy/run/`；环境变量模板见 `.env.example`。

## 模型平面边界

- 1.35 只允许模型权重、vLLM/推理进程、模型日志。
- 当前实测：`9977 GLM-OCR`、`9978 parsekit 版面（CPU 推理）`、`9979 版面（GPU）`、`9991 vLLM（Qwen3.5-9B + adapter-v5）` 就绪；
  但主机上仍有 `MinIO :9000`（root），不在白名单内，需确认迁出。
- 模型服务重启：见 `docs/runbook.md` 与 `infra/model-plane/README.md`。

### 公网穿透与自动兜底

- 默认优先使用公网 `39.107.239.208`：`35032→9977 OCR`、`35033→9978 Layout CPU`、`35034→9979 Layout GPU`、`35035→9991 Qwen`。
- 每个服务配置独立 fallback：`GLM_OCR_FALLBACK_BASE_URL`、`QWEN_FALLBACK_BASE_URL`、`SFT_FALLBACK_BASE_URL`、
  `LAYOUT_SERVICE_FALLBACK_URL` / `LAYOUT_SERVICE_FALLBACK_URLS`，默认指向 `192.168.188.75`。
- 连接失败、超时、429/5xx 会自动切换并记住可用端点；`MODEL_FAILOVER_PROBE_SECONDS`（默认 60 秒）后重试主端点。
- 4xx（如模型名错误）不会切换，直接返回，避免掩盖配置问题。

## 容器化（单机 Compose + Postgres）

```bash
cd infra/docker
cp .env.example .env      # 填 HANSON_SECRET_KEY / POSTGRES_PASSWORD
HANSON_RELEASE_TAG=r6-11 docker compose -p hanson-r1 up -d
```

- `platform-api`  / `engine-api` / `worker-prod` / `worker-explore` / `web` / `postgres` 默认启动；
- `redis`、`minio` 使用 `profiles: ["extras"]`，仅在需要时 `docker compose --profile extras up -d`；
- 应用镜像统一命名为 `hanson-r1-<service>:${HANSON_RELEASE_TAG:-latest}`；不传 `HANSON_RELEASE_TAG` 时与原 `latest` 行为一致；
- 灰度/回滚命令（先 api/web，后 engine/worker）见 [docs/runbook.md](../docs/runbook.md) 第 4 节；
- 模型平面仍指向 1.35 的 HTTP 端点（`GLM_OCR_BASE_URL` / `LAYOUT_SERVICE_URL` / `SFT_BASE_URL`），不把模型进程打进业务容器；
- 生产启动会校验 secret、Postgres、真实 OCR/抽取后端与 `HANSON_INLINE_JOBS=false`，不满足直接拒绝启动。
