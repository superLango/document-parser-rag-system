#!/usr/bin/env bash
# 将 new_app 七服务与基础设施部署到本地 kind 集群，并验证健康状态。
set -euo pipefail

CLUSTER_NAME="${CLUSTER_NAME:-hanson}"
NAMESPACE="${NAMESPACE:-hanson-standard}"
APP_IMAGE="${APP_IMAGE:-hanson-new-app:local}"
BASE_IMAGES=("postgres:16-alpine" "minio/minio:latest" "redis:7-alpine")
SERVICES=("api-gateway" "orchestration" "ocr" "agent" "sandbox" "recipe-registry" "review")

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NEW_APP_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
K8S_DIR="$NEW_APP_DIR/deploy/k8s/base"

export PATH="$PATH:$HOME/.local/bin"

echo "[1/5] 检查本地镜像"
for img in "$APP_IMAGE" "${BASE_IMAGES[@]}"; do
  if ! docker image inspect "$img" >/dev/null 2>&1; then
    echo "  本地缺少 $img，尝试拉取"
    docker pull "$img"
  fi
  echo "  ok $img"
done

echo "[2/5] 加载镜像到 kind 集群 $CLUSTER_NAME"
# kind v0.24 的 `kind load` 会带 --all-platforms，在 Docker 使用 containerd
# image store 时因缺少其它平台 blob 而失败；这里直接 save 后由节点 ctr 导入。
NODE="${CLUSTER_NAME}-control-plane"
for img in "$APP_IMAGE" "${BASE_IMAGES[@]}"; do
  echo "  loading $img"
  docker save --platform linux/amd64 "$img" | docker exec -i "$NODE" \
    ctr --namespace=k8s.io images import --digests=false -
done

echo "[3/5] 应用 K8s 清单"
kubectl apply -k "$K8S_DIR"

# 镜像 tag 不变时 Deployment spec 无变化，需要显式重启才能加载新镜像。
kubectl -n "$NAMESPACE" rollout restart deployment \
  api-gateway orchestration ocr agent sandbox recipe-registry review

echo "[4/5] 等待基础设施就绪"
for d in postgres minio redis; do
  kubectl -n "$NAMESPACE" rollout status "deployment/$d" --timeout=240s
done

echo "[5/5] 等待七个服务就绪"
for d in "${SERVICES[@]}"; do
  kubectl -n "$NAMESPACE" rollout status "deployment/$d" --timeout=300s
done

echo "--- pods ---"
kubectl -n "$NAMESPACE" get pods -o wide
echo "--- services ---"
kubectl -n "$NAMESPACE" get svc
echo "[k8s] DEPLOY DONE"
