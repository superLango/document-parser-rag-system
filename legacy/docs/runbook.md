# 运行手册（M5）

> 适用：平台 API/Web、引擎 API/worker、模型平面（公网 39.107.239.208 优先，192.168.188.75 兜底）。
> 责任人：平台运维（值班表另附）；模型平面由模型负责人 on-call。

## 1. 拓扑

```text
Ingress → Web / Platform API →（HTTP）→ Engine API →（HTTP）→ 模型平面（公网优先，192.168.188.75 兜底）
                                          └→ worker-prod / worker-explore / worker-human
Postgres（平台库）· 引擎数据卷（jobs/queues/feedback/recipes）
```

## 2. 日常检查（每日）

1. `GET /ready`（平台与引擎）均为 ok；
2. `GET /metrics` 抓取正常；Grafana 看板无红色面板；
3. `engine_jobs{status="queued"}` 不持续增长；
4. `engine_jobs{status="failed"}` 比例 < 2%；
5. `platform_documents{status="review"}` 积压不超过 1 个工作日；
6. `platform_errors_total` 无持续增长（计数器随进程重启归零，首个 ≥400 响应后才出现）；
7. `worker-prod` / `worker-explore` 最近一次启动日志包含 `worker watching pool=...`（空闲时不刷日志属正常）；
8. 宿主机磁盘剩余 > 15%（引擎数据卷与 Postgres 卷同盘，写满会导致任务状态无法落盘）；
9. 备份成功时间戳 < 24h，`HMAC-SHA256SUMS` 随包存在。

## 3. 启停

### 容器（单机 Compose，当前生产形态）

启动顺序必须是：**postgres → platform-api（内部执行 `alembic upgrade head`）→ engine-api → worker-prod/worker-explore → web**；
模型平面需先于任务提交就绪：默认走公网 `39.107.239.208`，公网不可达时自动切换到 `192.168.188.75`。

```bash
cd infra/docker
export HANSON_RELEASE_TAG=r6-11         # 当前发布 tag；缺省为 latest
docker compose -p hanson-r1 --env-file <env> up -d
docker compose -p hanson-r1 --env-file <env> ps
```

- 冷启动（保留卷）实测 18s 内 postgres/platform/engine 全部 healthy；
- 只重启某个服务：`docker compose -p hanson-r1 restart platform-api`；
- 停止但保留数据：`docker compose -p hanson-r1 down`（**不要加 `-v`**）。

### 本机（无容器）

```powershell
deploy/start_local.ps1        # API + worker + web
deploy/stop_local.ps1
```

### K8s（P2，未演练）

```bash
kubectl apply -k infra/k8s
kubectl -n metal-agent rollout status deploy/platform-api deploy/engine-api
kubectl -n metal-agent get pods -l plane=engine
```

### 模型平面（公网穿透 + 局域网兜底）

必须按顺序：`9977 GLM-OCR（seq12/8192/gpu0.4）→ 9978/9979 版面 → 9991 vLLM(base + adapter-v5，gpu0.38）`。
公网映射：`35032→9977`、`35033→9978`、`35034→9979`、`35035→9991`；SSH `35031→22`。
引擎优先公网，连接失败/超时/429/5xx 自动切 `192.168.188.75`，`MODEL_FAILOVER_PROBE_SECONDS` 后重试公网。

```bash
python -m metal_doc_agent.cli models check   # 显示实际使用的端点与模型名
```

离线评测可停 OCR/版面释放内存；恢复时先确认 `free -g` 与 swap（GLM 0.4 + Qwen 0.38 后仅余 ~4GB）。

## 4. 发布与回滚

### 容器 tag 灰度（已演练，推荐）

镜像名固定为 `hanson-r1-<service>:<tag>`，由 `HANSON_RELEASE_TAG` 选择版本。

```bash
cd infra/docker
export HANSON_RELEASE_TAG=<new-tag>

# 1) 构建新 tag
docker compose -p hanson-r1 --env-file <env> build platform-api engine-api worker-prod worker-explore web

# 2) 第一段：先切平台与前端，观察
docker compose -p hanson-r1 --env-file <env> up -d --no-deps platform-api web
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/platform/ready
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/

# 3) 第二段：再切引擎与 worker
docker compose -p hanson-r1 --env-file <env> up -d --no-deps engine-api worker-prod worker-explore

# 4) 一键回滚（保留上一 tag）
export HANSON_RELEASE_TAG=<prev-tag>
docker compose -p hanson-r1 --env-file <env> up -d --no-deps platform-api web engine-api worker-prod worker-explore
```

- 演练记录：`r6-baseline`（回滚基线）→ `r6-2` → `r6-3` → `r6-4` → `r6-10` → **`r6-11`（当前：引擎页面级容错；platform-api/web 仍为 r6-10）**；
- 回滚到 r6-10 只需对 `engine-api` / `worker-prod` / `worker-explore` 设 `HANSON_RELEASE_TAG=r6-10` 后 `up -d --no-deps` 这三个服务。
- 观察项：`platform_errors_total`、`engine_jobs{status="failed"}`、`/platform/ready`、web 首页、worker 启动日志。

### K8s（P2）

```bash
kubectl apply -k infra/k8s/overlays/canary   # 灰度
kubectl apply -k infra/k8s                  # 全量
kubectl -n metal-agent rollout undo deploy/platform-api
kubectl -n metal-agent rollout undo deploy/engine-api
```

配方/模型回滚：

```bash
# 配方：恢复 registry.json / 配方文件后重启 engine-api
python -m tools.recipe_lifecycle rollback <recipe_id> --actor ops
# 模型：切回上一个镜像 tag / adapter 目录，重启 9991（保持单实例）
```

## 5. 故障处理

| 现象 | 判断 | 处理 |
|---|---|---|
| 平台 5xx 激增 | `up{job="platform-api"}=0` 或多副本异常 | 查 Pod 日志、DB 连接；必要时回滚 |
| 数据库不可用 | `/platform/ready` 与登录返回 **503 `application/problem+json`**（detail=`database unavailable`） | 恢复 Postgres；连接恢复后 API 自动转 200，无需重启 |
| 任务积压 | `engine_jobs{status="queued"}>20` 10 分钟 | 扩 `worker-prod` 副本；检查模型端点 |
| 失败率 >5% | `engine_job_failure_ratio` 告警 | 按 `failure_code` 分类见 5.1；模型/OCR 故障则暂停入队并修复，**不得降级 mock 写假结果** |
| 内存/swap 满 | `.75` `free -g`、`load` 高 | 停 OCR/版面/重复 9991；按 9977→9978→9991 顺序重启 |
| 模型不可用 | `up{job="model-*"}=0` | 任务进入 review 并带 `failure_code`，修复后由人工复核或重跑 |
| 复核确认被拒 409 | `high_risk_fields_unreviewed` | 打开字段复核 tab，处理 high 字段后再确认 |
| 备份失败 | `backup_last_success_timestamp_seconds` 不更新 | 检查卷/对象存储；补跑 `infra/backup/backup.sh`；恢复前先校验 HMAC |
| 磁盘写满 | worker 日志 `OSError: [Errno 28] No space left on device` | 清理数据卷；因同盘无法写 state，任务可能停留 `running`，清理后等 stale recovery（默认 300s）重新入队 |
| 任务长期 `running` | job 心跳超过 300s 未更新 | 确认无原 worker 进程后，等待其他 worker 的 stale recovery 接管（`attempts` 会 +1） |
| OCR 单块超时/重试 | 日志 `slow block OCR page=... type=table elapsed≈90–130s` | 长表格响应的首次尝试可能丢失；流式 + 90s 超时 + 自动重试会恢复。连续出现时确认 `OCR_TABLE_INFLIGHT<=2`、`:9977` 健康且无并发压测任务 |

### 5.1 failure_code 对照

| failure_code | 含义 | 首要排查 |
|---|---|---|
| `invalid_input` | 文件缺失/不可解析/参数非法 | 上传文件、`.pdf` 是否加密、请求参数 |
| `layout_failed` | 版面服务（9978）不可用或失败 | `curl :9978/health`、`up{job="model-layout"}` |
| `ocr_failed` | GLM-OCR（9977）失败或 OCR 质量 0 | `:9977/v1/models`、vLLM 队列/显存、单表耗时 |
| `extract_failed` | Qwen/SFT（9991）抽取失败 | adapter-v5 是否加载、`/v1/models`、超时配置 |
| `timeout` | 工具/模型调用超时 | `METAL_DOC_TOOL_TIMEOUT`（默认 900s）、模型排队时长 |
| `engine_failed` | 其他引擎异常 | 引擎日志 `job_id` 上下文与堆栈 |

日志定位：平台访问日志为 JSON 行并带 `request_id`（响应头 `X-Request-ID` 同值）；引擎日志为 JSON 行并带 `job_id`，按 `job_id` 串联 worker 与编排步骤。

## 6. 升级路径与值班

- P1（服务不可用）：15 分钟内响应，1 小时内恢复或回滚；
- P2（质量/积压）：4 小时内响应；
- 升级联系人：平台运维 → 项目负责人 → 模型负责人。
- 交接班检查：`docker compose ps` 全 healthy、`/platform/ready` 全 true、队列无持续积压、最近备份 < 24h、未关闭的 P1/P2 工单。

## 7. 已知限制

- 三队列 worker 共享同一 JobStore，当前按 FIFO 消费；池隔离靠副本/节点与模型端点配额实现。
- 引擎已输出 `engine_pipeline_seconds_bucket` 直方图；长文档 SLO 仍受 OCR 吞吐约束（GLM-OCR 服务 `--max-num-seqs 12 / --max-num-batched-tokens 8192`、单表约 7–19s）。
- OCR 客户端默认流式（`GLM_OCR_STREAM=1`）、`GLM_OCR_TIMEOUT=90`（**空闲读超时，不是总时长**）、总并发 `OCR_MAX_INFLIGHT=16`、表格并发 `OCR_TABLE_INFLIGHT=2`；超大表格单块可能持续数十秒（新全量实测最长 ~48s），旧 bridge 网络下曾因超时簇放大到 300–500s。
- 全量压测（25 份去重文档 / 434 页，2026-11-02 `.75`+host）：**1764s、4.06s/页、中位 3.33s/页、p95 5.6s/页，全部文档 ≤300s（最慢 222s），失败块 0**；旧基线为 6559s / 15.1s/页 / 18/21 达标 / 11 个失败块。详见计划文档第 26.8 节。
- 版面服务公网优先 `35034`（GPU）/`35033`（CPU），局域网兜底 `9979`（GPU）/`9978`（CPU）；`LAYOUT_TIMEOUT=60` 自动切换。单页仍可能偶发超时，现已做**页面级容错**：失败页保留 PDF 文本层、写 `layout-*.json` 的 `error` 字段并继续处理其余页，整单不再中断，最终 `quality.status` 标记异常供人工复核。
- 多 worker 同时处理文档会各自占用表格并发配额（每进程 2），实测 4 并发表格显著退化（22 页 279s→605s）；生产应单文档串行，横向扩展需把表格并发做成全局配额。
- **worker 必须使用 host 网络**：Docker bridge 跨子网访问 `192.168.188.75` 时，图片 OCR 请求会间歇 90s 无响应（流式/非流式均出现，服务端日志显示已完成），端到端慢 4–9 倍；`compose.yaml` 已设置 `network_mode: host`，排障时不要改回 bridge。若必须用 bridge，先确认 NAT/MTU 正常。
- 备份已加密（AES-256-CBC/PBKDF2 + HMAC-SHA256 清单）；**异地存储尚未接入**，需运维提供目标与凭据。
- `platform_errors_total` 为进程内计数器：重启归零、首个 ≥400 响应后才出现在 `/platform/metrics`。
- 磁盘写满时任务状态无法落盘（state 与数据同盘），需人工清理后依赖 stale recovery。
- K8s 部署与回滚未演练（P2）；当前生产形态为单机 Compose + Postgres。
