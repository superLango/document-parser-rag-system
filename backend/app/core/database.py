"""SQLAlchemy 异步数据库配置模块。

本模块负责创建与 PostgreSQL 的异步连接资源，包含：

- 异步引擎（create_async_engine）：管理连接池
- 异步会话工厂（async_sessionmaker）
- DeclarativeBase 基类：所有 ORM 模型的基类
- get_db 依赖注入函数：为 FastAPI 路由提供数据库会话

使用方式（在路由中依赖注入）：
    from app.core.database import get_db

    @app.get("/items")
    async def list_items(db: AsyncSession = Depends(get_db)):
        ...

注意：
    DATABASE_URL 必须使用 asyncpg 驱动（postgresql+asyncpg://）。
    连接池参数 pool_size=10, max_overflow=20, pool_pre_ping=True，
    可在 settings.DATABASE_URL 修改后自动适配。
"""

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

# 创建异步引擎
# pool_size: 连接池中持久保留的连接数
# max_overflow: 超出 pool_size 后允许临时创建的连接数
# pool_pre_ping: 每次借出连接前发送心跳，避免使用已失效的连接
engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    echo=settings.DEBUG,
)

# 异步会话工厂
# expire_on_commit=False: 提交后对象属性仍可用，避免异步场景下的懒加载问题
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    """所有 ORM 模型的声明式基类。

    使用方式：
        from app.core.database import Base

        class Document(Base):
            __tablename__ = "documents"
            ...
    """


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 数据库会话依赖。

    生成一个异步会话并在请求结束后自动关闭，确保连接归还到连接池。
    发生异常时会自动回滚事务。

    Yields:
        AsyncSession: 当前请求的数据库异步会话。
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            # 发生异常时回滚事务，避免脏数据残留
            await session.rollback()
            raise
        finally:
            await session.close()
