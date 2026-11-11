#!/usr/bin/env bash
# Load Calico images into a kind node (used by the NetworkPolicy verification cluster).
set -euo pipefail

NODE="${NODE:-hanson-calico-control-plane}"
IMAGES=(
  "calico/cni:v3.28.0"
  "calico/node:v3.28.0"
  "calico/kube-controllers:v3.28.0"
)

for img in "${IMAGES[@]}"; do
  echo "loading $img"
  docker save --platform linux/amd64 "$img" | docker exec -i "$NODE" \
    ctr --namespace=k8s.io images import --digests=false -
done

echo "--- calico images in $NODE ---"
docker exec "$NODE" ctr --namespace=k8s.io images ls | grep calico
