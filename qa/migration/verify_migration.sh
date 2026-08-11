#!/usr/bin/env bash
# M9 数据库迁移与种子验证脚本（测试库专用，不影响开发库 hanson_doc_rag）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PSQL_BIN="${PSQL_BIN:-/home/grainuser/pgsql18/bin/psql}"
TEST_DB="hanson_doc_rag_test"
TEST_URL="postgresql+asyncpg://postgres@localhost:5432/${TEST_DB}"

echo "[1/6] 重建测试库 ${TEST_DB}"
"$PSQL_BIN" -h localhost -U postgres -d postgres -q \
  -c "DROP DATABASE IF EXISTS ${TEST_DB};" \
  -c "CREATE DATABASE ${TEST_DB};"

echo "[2/6] 迁移 upgrade head（首次）"
cd "${ROOT}/backend"
DATABASE_URL="${TEST_URL}" .venv/bin/alembic upgrade head

echo "[3/6] 重复 upgrade head（幂等校验）"
DATABASE_URL="${TEST_URL}" .venv/bin/alembic upgrade head

echo "[4/6] 种子数据校验"
ROLES=$("$PSQL_BIN" -h localhost -U postgres -d "${TEST_DB}" -tAc "select count(*) from roles;")
PERMS=$("$PSQL_BIN" -h localhost -U postgres -d "${TEST_DB}" -tAc "select count(*) from permissions;")
MATRIX=$("$PSQL_BIN" -h localhost -U postgres -d "${TEST_DB}" -tAc "select count(*) from role_permissions;")
SUPER_MATRIX=$("$PSQL_BIN" -h localhost -U postgres -d "${TEST_DB}" -tAc "select count(*) from role_permissions rp join roles r on r.id=rp.role_id where r.code='super_admin';")
echo "roles=${ROLES} permissions=${PERMS} role_permissions=${MATRIX} super_admin_matrix=${SUPER_MATRIX}"
[ "$ROLES" -eq 4 ] || { echo "FAIL: 期望 4 个系统角色"; exit 1; }
[ "$PERMS" -eq 11 ] || { echo "FAIL: 期望 11 个权限点"; exit 1; }
[ "$SUPER_MATRIX" -eq 11 ] || { echo "FAIL: super_admin 应拥有全部 11 个权限点"; exit 1; }

echo "[5/6] downgrade -> upgrade 往返"
DATABASE_URL="${TEST_URL}" .venv/bin/alembic downgrade 001_initial_auth
DATABASE_URL="${TEST_URL}" .venv/bin/alembic upgrade head

echo "[6/6] 迁移验证通过"
