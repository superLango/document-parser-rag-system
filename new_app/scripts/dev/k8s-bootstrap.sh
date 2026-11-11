#!/usr/bin/env bash
set -euo pipefail

BIN="${HOME}/.local/bin"
mkdir -p "${BIN}"

KIND_VERSION="v0.24.0"
KUBECTL_VERSION="v1.30.0"
KIND_URL="https://ghproxy.net/https://github.com/kubernetes-sigs/kind/releases/download/${KIND_VERSION}/kind-linux-amd64"
KUBECTL_URLS=(
  "https://storage.googleapis.com/kubernetes-release/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl"
  "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl"
  "https://mirrors.aliyun.com/kubernetes/kubernetes-release/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl"
)

if [ ! -x "${BIN}/kind" ]; then
  echo "[k8s] downloading kind ${KIND_VERSION}"
  curl -fL --retry 3 --retry-delay 2 -o "${BIN}/kind" "${KIND_URL}"
  chmod +x "${BIN}/kind"
fi

if [ ! -x "${BIN}/kubectl" ]; then
  echo "[k8s] downloading kubectl ${KUBECTL_VERSION}"
  for url in "${KUBECTL_URLS[@]}"; do
    if curl -fL --retry 2 --retry-delay 2 -o "${BIN}/kubectl" "${url}"; then
      chmod +x "${BIN}/kubectl"
      break
    fi
    echo "[k8s] kubectl mirror failed: ${url}"
  done
fi

export PATH="${BIN}:${PATH}"
kind version
kubectl version --client

if ! kind get clusters 2>/dev/null | grep -qx "hanson"; then
  echo "[k8s] creating kind cluster hanson"
  kind create cluster --name hanson --image kindest/node:v1.30.0 --wait 180s
fi

echo "[k8s] applying namespace"
kubectl apply -f /mnt/f/hanson/hanson_doc_parse/new_app/deploy/k8s/base/namespace.yaml
kubectl get nodes
kubectl get namespace hanson-standard
echo "[k8s] DONE"
