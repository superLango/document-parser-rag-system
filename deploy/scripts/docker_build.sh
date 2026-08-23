#!/usr/bin/env bash
# 构建 backend / frontend 镜像
set -euo pipefail
cd "$(dirname "$0")/.."
echo "==> 构建 backend 镜像（含小模型，约 9~10G，耗时较长）"
docker build -f backend/Dockerfile -t hansondoc-backend .
echo "==> 构建 frontend 镜像"
docker build -f frontend/Dockerfile -t hansondoc-frontend .
echo "构建完成"
