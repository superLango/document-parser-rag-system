#!/usr/bin/env bash
# 从现有系统 PostgreSQL 导出全库（schema+data，不含 owner/权限），供容器初始化
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p backup
echo "导出系统 PostgreSQL -> backup/dump.sql ..."
/home/grainuser/pgsql18/bin/pg_dump \
    -h 127.0.0.1 -p 5432 -U postgres -d hanson_doc_rag \
    --no-owner --no-privileges \
    -f backup/dump.sql
echo "导出完成：$(du -h backup/dump.sql | cut -f1)"
