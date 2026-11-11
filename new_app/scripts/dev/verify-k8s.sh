#!/usr/bin/env bash
set -euo pipefail
export PATH="${HOME}/.local/bin:${PATH}"

echo "--- clusters ---"
kind get clusters
echo "--- nodes ---"
kubectl get nodes -o wide
echo "--- namespace ---"
kubectl get namespace hanson-standard
echo "--- cluster-info ---"
kubectl cluster-info
