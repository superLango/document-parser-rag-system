#!/usr/bin/env bash
# 检查编排库的迁移版本、表与外键/唯一约束。
set -euo pipefail

NAMESPACE="${NAMESPACE:-hanson-standard}"
export PATH="$PATH:$HOME/.local/bin"

PSQL=(kubectl -n "$NAMESPACE" exec deploy/postgres -- psql -U hanson -d hanson -t -A)

echo "--- alembic_version ---"
"${PSQL[@]}" -c "select version_num from alembic_version;"

echo "--- tables ---"
"${PSQL[@]}" -c \
  "select tablename from pg_tables where schemaname = current_schema() order by tablename;"

echo "--- foreign keys / unique constraints ---"
"${PSQL[@]}" -c \
  "select conrelid::regclass, conname, contype from pg_constraint \
   where connamespace = current_schema()::regnamespace and contype in ('f','u') \
   order by 1, 2;"
