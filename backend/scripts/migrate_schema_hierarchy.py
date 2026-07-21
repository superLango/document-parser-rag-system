"""Schema 模型迁移脚本 - 添加父子层级与抽取示例字段。

执行步骤：
1. ALTER TABLE schema_configs 添加新列（parent_id, sample_fields, is_active, sort_order）
2. 将现有 Schema 数据迁移到"默认分类"父节点下
3. 同步 is_active 字段（基于 is_template 反向）

执行方式：
    cd backend && source venv/bin/activate && python scripts/migrate_schema_hierarchy.py

注意：该迁移是幂等的，可重复执行。已存在的列会跳过 ALTER。
"""

import asyncio
import sys
import uuid
from pathlib import Path

# 加入 backend 目录到 sys.path，便于直接运行
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import text

from app.core.database import AsyncSessionLocal, engine


DEFAULT_CATEGORY_NAME = "默认分类"
DEFAULT_CATEGORY_DESCRIPTION = "迁移期间自动创建的默认父分类"


async def column_exists(conn, table_name: str, column_name: str) -> bool:
    """检查表中是否存在某列。"""
    result = await conn.execute(
        text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :table AND column_name = :column"
        ),
        {"table": table_name, "column": column_name},
    )
    return result.scalar() is not None


async def get_default_category_id(conn) -> uuid.UUID:
    """获取或创建默认父分类节点。"""
    result = await conn.execute(
        text(
            "SELECT id FROM schema_configs "
            "WHERE parent_id IS NULL AND name = :name LIMIT 1"
        ),
        {"name": DEFAULT_CATEGORY_NAME},
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        return existing

    # 创建默认分类
    new_id = uuid.uuid4()
    await conn.execute(
        text(
            "INSERT INTO schema_configs (id, parent_id, name, description, "
            "schema_definition, sample_fields, is_active, sort_order, is_template) "
            "VALUES (:id, NULL, :name, :desc, '[]'::jsonb, '{}'::jsonb, TRUE, 0, FALSE)"
        ),
        {"id": new_id, "name": DEFAULT_CATEGORY_NAME, "desc": DEFAULT_CATEGORY_DESCRIPTION},
    )
    return new_id


async def migrate():
    """执行迁移。"""
    async with engine.begin() as conn:
        # 1. 添加新列（如果不存在）
        new_columns = [
            ("parent_id", "UUID REFERENCES schema_configs(id) ON DELETE CASCADE"),
            ("sample_fields", "JSONB NOT NULL DEFAULT '{}'::jsonb"),
            ("is_active", "BOOLEAN NOT NULL DEFAULT TRUE"),
            ("sort_order", "INTEGER NOT NULL DEFAULT 0"),
        ]
        for col_name, col_def in new_columns:
            if await column_exists(conn, "schema_configs", col_name):
                print(f"[skip] column already exists: {col_name}")
            else:
                await conn.execute(
                    text(f"ALTER TABLE schema_configs ADD COLUMN {col_name} {col_def}")
                )
                print(f"[ok] added column: {col_name}")

        # 2. 创建 parent_id 索引（如果不存在）
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_schema_configs_parent_id "
                "ON schema_configs (parent_id)"
            )
        )
        print("[ok] index ensured: ix_schema_configs_parent_id")

    # 3. 数据迁移：将现有 Schema 挂到默认分类下
    async with AsyncSessionLocal() as session:
        async with session.begin():
            # 获取或创建默认分类
            default_cat_id = await get_default_category_id(session)
            print(f"[ok] default category id: {default_cat_id}")

            # 同步 is_active 字段：基于 is_template 反向
            await session.execute(
                text(
                    "UPDATE schema_configs SET is_active = (NOT is_template) "
                    "WHERE is_active IS NULL OR is_active = TRUE"
                )
            )

            # 将所有 parent_id IS NULL 且 name != 默认分类 的现有 Schema 挂到默认分类下
            result = await session.execute(
                text(
                    "UPDATE schema_configs SET parent_id = :cat_id "
                    "WHERE parent_id IS NULL AND name != :cat_name "
                    "RETURNING id, name"
                ),
                {"cat_id": default_cat_id, "cat_name": DEFAULT_CATEGORY_NAME},
            )
            migrated = result.fetchall()
            print(f"[ok] migrated {len(migrated)} schemas to default category")
            for row in migrated:
                print(f"     - {row[1]} ({row[0]})")

    # 4. 验证结果
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text(
                "SELECT "
                "  (SELECT COUNT(*) FROM schema_configs WHERE parent_id IS NULL) AS parents, "
                "  (SELECT COUNT(*) FROM schema_configs WHERE parent_id IS NOT NULL) AS children"
            )
        )
        counts = result.one()
        print(f"\n=== 迁移完成 ===")
        print(f"父分类数: {counts[0]}")
        print(f"子 Schema 数: {counts[1]}")


if __name__ == "__main__":
    asyncio.run(migrate())
