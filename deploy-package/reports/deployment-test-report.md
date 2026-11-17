# 部署包测试报告

- 日期：2026-11-15
- 包版本：`2026.11.15`
- 测试环境：本机 WSL2（Ubuntu），Docker Server `29.7.2`，Docker Compose `5.4.0`
- 测试方式：使用交付包中的镜像和 compose 启动独立测试栈，不复用现有生产栈
- 模型：GLM-OCR、PP-DocLayoutV3、Qwen3.6-35B-A3B-NVFP4 均调用模型服务器 `192.168.1.35`

## 1. 结论

**通过。** 交付镜像可以在 WSL 上独立启动，11 个容器全部 healthy；三个模型端点均可达；使用真实模型完成 22 页 PDF 解析，一站式解析页面正常显示原文与结构化结果。

## 2. 测试栈配置

| 项 | 值 |
| --- | --- |
| Compose 项目 | `hanson-deploy-test` |
| API 端口 | `28000` |
| Web 端口 | `25173` |
| PostgreSQL | `25432` |
| Redis | `26379` |
| MinIO | `29000 / 29001` |
| 容器网段 | `10.89.0.0/16` |
| Parser 资产 | `1.7.40`，`PARSER_ASSET_REQUIRED=true` |
| 人工审核 | 开启（最终 `HUMAN_REVIEW`，结果已可读） |

## 3. 镜像与容器

交付归档 `images/hanson-runtime-images.tar.gz`：

- 大小：362 MB
- SHA256 校验：通过
- 包含 6 个镜像：
  - `hanson-new-app:local`
  - `hanson-web:local`
  - `hanson-sandbox-runtime:local`
  - `postgres:16-alpine`
  - `redis:7-alpine`
  - `minio/minio:latest`

独立栈容器状态：

```text
agent             healthy
api-gateway       healthy
minio             running
ocr               healthy
orchestration     healthy
postgres          healthy
recipe-registry   healthy
redis             healthy
review            healthy
sandbox           healthy
web               healthy
```

## 4. 模型连通性

执行 `models/check-models.sh`：

```text
OK   GLM-OCR  http://192.168.1.35:9977/v1/models
OK   Layout   http://192.168.1.35:9978/healthz
OK   Qwen     http://192.168.1.35:9988/v1/models
```

测试容器内也验证了三个地址均返回 200，说明应用网络可以访问模型服务器。

## 5. 端到端解析

样本：`samples/smoke.pdf`（GB/T 1591-2018，22 页）。

| 项 | 结果 |
| --- | --- |
| 上传接口 | `POST /api/v1/integration/upload` 返回 `code=0` |
| task_id | `dfc818cc-1f4c-41e2-ac44-a541f65a69a7` |
| document_id | `db39338c-7188-4800-91d3-9da8e5b963f3` |
| OCR 后端 | `layout_first` |
| 页数 / 版面块 | 22 页 / 275 块 |
| OCR 告警 | 0 |
| 状态流转 | OCR processing → completed → extract running → completed |
| 结构化记录 | 2056 条 |
| 分类 | 标准信息 1、化学成分 712、室温拉伸 67、冲击试验 27、弯曲 1、外观质量 830、尺寸 335、超声波检验 83 |
| 结果接口 | `code=0`，`summary.total_records=2056` |

说明：版面模型和 GLM-OCR 均通过模型服务器真实调用，不是 fake/本地回退。

## 6. 页面验证

访问 `http://localhost:25173/integration/task/{task_id}`：

| 检查项 | 结果 |
| --- | --- |
| HTTP 状态 | 200 |
| 标题 | 一站式标准解析 |
| 左侧菜单 `<aside>` | 0 |
| 导航 `<nav>` | 0 |
| 原文 PDF | iframe 可见，`/v1/documents/{id}/file` 返回 200、`application/pdf`、`%PDF-` |
| 结构化结果 | 标准信息、化学成分、室温拉伸、冲击试验等正常显示 |
| 截图 | `reports/deploy-test-page.png` |

## 7. 任务清理验证

执行 `scripts/reset-tasks.sh --yes`：

```text
before: documents=1 runs=1 artifacts=41 integration_tasks=1
after:  documents=1 runs=0 artifacts=0  integration_tasks=0
```

文档和原始 PDF 保留，任务、run、artifact 元数据和对接任务全部清除。

当前生产实例也已执行清理：

```text
documents=30
runs=0
artifacts=0
integration_tasks=0
```

## 8. 测试中发现并修复的问题

| 问题 | 现象 | 修复 |
| --- | --- | --- |
| 部署 compose 缺少服务间地址 | 上传返回 `orchestration unavailable` | 补齐 `ORCHESTRATION_URL`、`OCR_URL`、`AGENT_*_URL`、`REVIEW_*_URL` 等容器内地址 |
| Docker 自动分配网段与模型服务器冲突 | 测试网络拿到 `192.168.0.0/20`，覆盖 `192.168.1.35` 路由，模型全部不可达 | compose 固定 `HANSON_NETWORK_SUBNET=10.88.0.0/16`，测试使用 `10.89.0.0/16` |
| nginx 缓存 gateway 旧 IP | 重建 gateway 后 Web 访问 `/api/` 返回 502 | nginx 增加 Docker DNS 动态解析，`proxy_pass` 使用变量 |
| 测试栈网关重建 | 仅重建 gateway 时 web 仍可用 | 已通过动态 DNS 修复，无需重启 web |

## 9. 未执行项

- 未实际重启模型服务器上的三个模型，避免影响当前共享模型服务；只验证了三个端点、启动脚本语法和 `check-models.sh`。
- 未在目标客户服务器上执行部署；本次验证环境为本机 WSL2。

## 10. 测试结束处理

测试栈已在验证完成后停止并删除测试卷，生产实例保持运行：

- 生产 API：`http://localhost:18000`
- 生产 Web：`http://localhost:15173`
- 生产文档：30 份
- 生产任务：0
