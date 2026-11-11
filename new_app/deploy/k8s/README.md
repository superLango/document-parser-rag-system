# K8s 部署（本地 kind）

M0 已落地命名空间、基础设施与七个服务的 Deployment/Service；HPA、NetworkPolicy、沙箱节点隔离在 M4 补齐。

## 清单

| 文件 | 内容 |
|---|---|
| `base/namespace.yaml` | `hanson-standard` 命名空间 |
| `base/infra.yaml` | Postgres、MinIO、Redis（Deployment + Service + PVC） |
| `base/apps.yaml` | 七服务 Deployment/Service 与公共 ConfigMap |
| `base/kustomization.yaml` | 汇总入口，配合 `kubectl apply -k` |

## 端口

| 组件 | 集群内端口 | 访问方式 |
|---|---|---|
| api-gateway | 8000 | NodePort `30080` |
| orchestration | 8001 | ClusterIP |
| ocr | 8002 | ClusterIP |
| agent | 8003 | ClusterIP |
| sandbox | 8004 | ClusterIP |
| recipe-registry | 8005 | ClusterIP |
| review | 8006 | ClusterIP |
| postgres | 5432 | ClusterIP |
| minio | 9000 / 9001 | ClusterIP |
| redis | 6379 | ClusterIP |

## 脚本

| 脚本 | 用途 |
|---|---|
| `scripts/dev/k8s-bootstrap.sh` | 安装 kind/kubectl，创建集群与命名空间 |
| `scripts/dev/k8s-deploy.sh` | 加载镜像、apply 清单、重启服务、等待就绪 |
| `scripts/dev/k8s-smoke.sh` | 集群内七服务与基础设施健康检查 + NodePort |
| `scripts/dev/k8s-e2e.sh` | 经 NodePort 上传 → run → 结果 |
| `scripts/dev/verify-k8s.sh` | 集群、节点、命名空间状态 |
| `scripts/dev/k8s-inspect-run.sh` | 查询 run / run_stages / run_events 原始数据 |
| `scripts/dev/k8s-db-check.sh` | 检查 Alembic 版本、表与外键/唯一约束 |
| `scripts/dev/k8s-retry-check.sh` | 注入一次 ocr 失败，验证阶段重试与事件序列 |
| `scripts/dev/k8s-check-delete.sh` | 运行中删除文档，验证取消、级联清理与对象删除 |

## 约束

- 沙箱节点与业务节点隔离（M4 落地）。
- 网关是唯一公网入口。
- 本地开发/测试对象存储使用 MinIO。
- 模型操作在模型服务器执行，不在 K8s 业务集群内。

## 已知问题

- `kind load docker-image` 在 Docker 使用 containerd image store 时会因 `--all-platforms` 报 `content digest ... not found`；部署脚本改用 `docker save --platform linux/amd64 | ctr images import`。
- 镜像 tag 固定为 `hanson-new-app:local` 时，重新构建后需 `kubectl rollout restart` 才会加载新镜像；`k8s-deploy.sh` 已包含该步骤。
