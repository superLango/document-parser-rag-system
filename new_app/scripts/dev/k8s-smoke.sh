#!/usr/bin/env bash
# 在 kind 集群内验证七服务、基础设施与网关代理是否可用。
set -euo pipefail

NAMESPACE="${NAMESPACE:-hanson-standard}"
CLUSTER_NAME="${CLUSTER_NAME:-hanson}"
APP_IMAGE="${APP_IMAGE:-hanson-new-app:local}"

export PATH="$PATH:$HOME/.local/bin"

echo "[1/3] 集群内七服务与基础设施健康检查"
kubectl -n "$NAMESPACE" run smoke-health --rm -i --restart=Never \
  --image="$APP_IMAGE" --image-pull-policy=IfNotPresent \
  -- python - <<'PY'
import json
import socket
import urllib.request

services = {
    "api-gateway": 8000,
    "orchestration": 8001,
    "ocr": 8002,
    "agent": 8003,
    "sandbox": 8004,
    "recipe-registry": 8005,
    "review": 8006,
}
ok = True
for name, port in services.items():
    try:
        with urllib.request.urlopen(f"http://{name}:{port}/healthz", timeout=5) as r:
            body = json.loads(r.read())
        print(f"OK   {name}:{port} {body}")
    except Exception as exc:  # noqa: BLE001
        ok = False
        print(f"FAIL {name}:{port} {exc}")

for name, port in {"postgres": 5432, "redis": 6379}.items():
    try:
        with socket.create_connection((name, port), timeout=5):
            print(f"OK   {name}:{port} tcp")
    except Exception as exc:  # noqa: BLE001
        ok = False
        print(f"FAIL {name}:{port} {exc}")

try:
    with urllib.request.urlopen("http://minio:9000/minio/health/live", timeout=5) as r:
        print(f"OK   minio:9000 status={r.status}")
except Exception as exc:  # noqa: BLE001
    ok = False
    print(f"FAIL minio:9000 {exc}")

raise SystemExit(0 if ok else 1)
PY

echo "[2/3] 网关 -> 编排链路"
kubectl -n "$NAMESPACE" run smoke-api --rm -i --restart=Never \
  --image="$APP_IMAGE" --image-pull-policy=IfNotPresent \
  -- python -c "import urllib.request; r=urllib.request.urlopen('http://api-gateway:8000/v1/documents', timeout=10); print('OK /v1/documents', r.status, r.read()[:200])"

echo "[3/3] NodePort 30080（从 WSL 宿主机）"
NODE_IP="$(docker inspect "${CLUSTER_NAME}-control-plane" \
  --format '{{(index .NetworkSettings.Networks "kind").IPAddress}}')"
echo "  node ip: $NODE_IP"
curl -fsS "http://$NODE_IP:30080/healthz" && echo
curl -fsS "http://$NODE_IP:30080/v1/documents" | head -c 200 && echo
echo "[k8s] SMOKE DONE"
