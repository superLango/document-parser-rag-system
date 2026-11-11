import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import settings


class Base(DeclarativeBase):
    pass


engine = create_async_engine(settings.async_database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
ALEMBIC_INI = Path(__file__).parent / "alembic.ini"


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


def _upgrade_schema() -> None:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", settings.async_database_url)
    command.upgrade(config, "head")


async def init_db() -> None:
    # Alembic 同步 API 内部自行管理事件循环，放到线程中避免与外层事件循环冲突。
    await asyncio.to_thread(_upgrade_schema)
