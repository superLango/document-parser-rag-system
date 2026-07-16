"""pytest 全局配置与公共 fixture。

本模块为后端测试体系提供：
- pytest-asyncio 自动模式下的异步 fixture
- 基于 SQLite 内存数据库的测试引擎（使用 StaticPool 保证单连接共享，
  避免 :memory: 每连接独立库的陷阱），无需依赖外部 PostgreSQL
- FastAPI 测试客户端（httpx.AsyncClient + ASGITransport），并覆盖
  ``get_db`` 依赖以接入测试数据库
- 认证相关 fixture：JWT 令牌头、预置测试用户

所有测试均不依赖外部服务（PostgreSQL / Redis / MinIO / vLLM），
模型中使用的 PostgreSQL UUID 类型在 SQLite 上由 SQLAlchemy 自动降级。
"""

import asyncio
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

# 导入应用与核心模块
from app.core.database import Base, get_db
from app.core.security import create_access_token, hash_password
from app.models.user import User

# 显式导入所有模型，确保它们注册到 Base.metadata，
# 以便 create_all 能创建全部表
import app.models.document  # noqa: F401
import app.models.schema_model  # noqa: F401
import app.models.task  # noqa: F401
import app.models.term  # noqa: F401
import app.models.user  # noqa: F401


def _build_test_engine():
    """创建 SQLite 内存测试引擎。

    使用 StaticPool 复用同一底层连接，确保 ``:memory:`` 数据库在
    多个会话之间共享数据（默认情况下 SQLite 内存库每个连接独立）。
    """
    return create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


@pytest_asyncio.fixture
async def test_engine():
    """每个测试函数独立的 SQLite 内存引擎，并预建全部表。

    Yields:
        AsyncEngine: 已创建好全部表的异步引擎。
    """
    engine = _build_test_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """提供绑定到测试引擎的异步会话，用于直接操作数据库。

    与 ``client`` fixture 共享同一引擎（StaticPool 单连接），
    因此通过本会话写入的数据对测试客户端可见。
    """
    session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    async with session_factory() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def client(test_engine) -> AsyncGenerator[AsyncClient, None]:
    """FastAPI 测试客户端，覆盖 ``get_db`` 依赖以使用测试数据库。

    通过 ``app.dependency_overrides`` 将 ``get_db`` 替换为绑定到
    SQLite 测试引擎的会话工厂，使所有端点在无外部数据库环境下可运行。

    Yields:
        AsyncClient: 已配置好 ASGI 传输的异步 HTTP 客户端。
    """
    # 延迟导入，避免在模块加载阶段触发应用初始化
    from app.main import app

    session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        """覆盖生产 get_db，使用测试引擎会话。"""
        async with session_factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    # 清理依赖覆盖，避免影响其他测试
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def seed_user(db_session) -> dict:
    """在测试数据库中预置一名激活用户，返回用户对象与认证信息。

    Returns:
        dict: 包含 user / username / password / token / headers 的字典。
    """
    user = User(
        username="testuser",
        email="test@example.com",
        hashed_password=hash_password("testpass123"),
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    token = create_access_token({"sub": user.username})
    return {
        "user": user,
        "username": user.username,
        "password": "testpass123",
        "token": token,
        "headers": {"Authorization": f"Bearer {token}"},
    }


@pytest.fixture
def auth_headers() -> dict:
    """生成测试用 JWT 认证头。

    不依赖数据库，仅用于不需要校验用户真实存在的场景
    （例如直接测试 token 解析逻辑）。
    """
    token = create_access_token({"sub": "testuser"})
    return {"Authorization": f"Bearer {token}"}
