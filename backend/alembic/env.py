"""Alembic 异步迁移环境配置模块。

本模块为 Alembic 提供异步数据库迁移支持，核心流程：
1. 从 ``app.core.config.settings`` 读取 ``DATABASE_URL``
2. 创建异步引擎（``create_async_engine``）
3. 在 ``run_sync`` 回调中执行 ``context.configure`` + ``run_migrations``
4. ``target_metadata`` 指向 ``Base.metadata``，导入 ``app.models`` 确保全部表被检测

使用方式：
    cd backend
    alembic revision --autogenerate -m "create tables"
    alembic upgrade head
"""

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config, AsyncEngine

from alembic import context

# 从 alembic.ini 加载日志配置
config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 导入应用配置与 ORM 基类
from app.core.config import settings  # noqa: E402
from app.core.database import Base  # noqa: E402

# 导入全部 ORM 模型，确保 Alembic autogenerate 能检测到所有表
from app.models import *  # noqa: E402, F401, F403

# target_metadata 指向 Base.metadata，供 autogenerate 对比差异
target_metadata = Base.metadata

# 从应用配置动态覆盖 sqlalchemy.url
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)


def run_migrations_offline() -> None:
    """以离线模式生成迁移 SQL（不连接数据库）。

    适用于 CI/CD 环境中仅生成 SQL 脚本而不实际执行的场景。
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """在同步连接上下文中执行迁移。

    由 ``run_sync`` 调用，配置 Alembic context 并运行迁移。
    """
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """以异步模式执行迁移。

    创建异步引擎，获取连接后通过 ``run_sync`` 执行同步迁移逻辑。
    """
    connectable: AsyncEngine = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """以在线模式执行迁移（异步引擎）。"""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
