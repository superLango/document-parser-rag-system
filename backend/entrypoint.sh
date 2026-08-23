#!/bin/bash
# 等待 PostgreSQL 就绪 → 执行迁移 → 启动命令（uvicorn / arq）
set -e

echo "[entrypoint] 等待 PostgreSQL ${POSTGRES_HOST:-postgres}:${POSTGRES_PORT:-5432} ..."
for i in $(seq 1 60); do
    if python - <<'CHECK'
import asyncio, os
async def main():
    import asyncpg
    dsn = os.environ.get("DATABASE_URL", "").replace("postgresql+asyncpg://", "postgresql://")
    try:
        conn = await asyncio.wait_for(asyncpg.connect(dsn), timeout=3)
        await conn.close()
        raise SystemExit(0)
    except Exception:
        raise SystemExit(1)
asyncio.run(main())
CHECK
    then
        echo "[entrypoint] PostgreSQL 就绪"
        break
    fi
    echo "[entrypoint] 等待数据库... ($i)"
    sleep 3
done

echo "[entrypoint] 执行数据库迁移 ..."
alembic upgrade head

echo "[entrypoint] 启动: $*"
exec "$@"
