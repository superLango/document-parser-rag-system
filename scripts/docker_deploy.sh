#!/usr/bin/env bash
# 部署：导出数据 + 启动全部服务（首次 PG 自动初始化数据）
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] || cp .env.example .env
echo "==> 导出数据库（首次部署需要）"
bash scripts/db_export.sh
echo "==> 启动服务"
docker compose up -d
echo "==> 等待就绪"
docker compose ps
echo "前端: http://<host>:18080  后端接口: http://<host>:18000  PG: 15432  Redis: 16379  MinIO: 19000"
