#!/bin/bash
# 分段导出镜像(专为U盘≤4G设计) + 生成校验和
# 用法: ./export_images.sh <输出目录>
set -euo pipefail

OUT="${1:-/home/grainuser/hansonDoc_RAG/deploy_images}"
mkdir -p "$OUT"

echo "==> 保存 backend 镜像 (6.86GB, 分3段)"
docker save hansondoc-backend:latest | split -b 2G - "$OUT/hansondoc-backend.tar.part_" 
echo "  done"

echo "==> 保存 frontend 镜像 (67MB)"
docker save hansondoc-frontend:latest > "$OUT/hansondoc-frontend.tar"

echo "==> 生成校验和"
cd "$OUT"
sha256sum hansondoc-backend.tar.part_* hansondoc-frontend.tar > SHA256SUMS

echo "==> 输出清单"
ls -la "$OUT"
echo "完成. 拷贝整个 $OUT 目录到U盘(每文件≤2G, 安全)."
