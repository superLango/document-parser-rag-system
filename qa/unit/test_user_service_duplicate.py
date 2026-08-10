"""L1 单元测试：用户服务历史隐患复测（空邮箱重复校验、并发唯一约束）。"""

import uuid

import pytest

from app.core.exceptions import BusinessException, ErrorCode
from app.core.security import hash_password
from app.models.user import User
from app.schemas.user import UserCreate
from app.services import user_service


async def _operator(db_session) -> User:
    user = User(
        username=f"op_{uuid.uuid4().hex[:8]}",
        hashed_password=hash_password("Test@1234"),
        is_superuser=True,
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def test_create_users_with_null_email_no_false_conflict(db_session):
    """REG-01：email 为空时不得把 email IS NULL 当作冲突条件。"""
    operator = await _operator(db_session)
    name_a = f"na_{uuid.uuid4().hex[:6]}"
    name_b = f"nb_{uuid.uuid4().hex[:6]}"
    first = UserCreate(username=name_a, password="Test@1234", email=None)
    second = UserCreate(username=name_b, password="Test@1234", email=None)
    u1 = await user_service.create_user(db_session, operator, first)
    u2 = await user_service.create_user(db_session, operator, second)
    assert u1.username == name_a
    assert u2.username == name_b
    assert u1.email is None and u2.email is None


async def test_create_duplicate_username_rejected(db_session):
    operator = await _operator(db_session)
    name = f"du_{uuid.uuid4().hex[:6]}"
    await user_service.create_user(
        db_session, operator, UserCreate(username=name, password="Test@1234")
    )
    with pytest.raises(BusinessException) as exc:
        await user_service.create_user(
            db_session, operator, UserCreate(username=name, password="Test@1234")
        )
    assert exc.value.code == ErrorCode.BUSINESS_USER_EXISTS


async def test_create_duplicate_email_rejected(db_session):
    operator = await _operator(db_session)
    email = f"same_{uuid.uuid4().hex[:6]}@example.com"
    await user_service.create_user(
        db_session,
        operator,
        UserCreate(username=f"ma_{uuid.uuid4().hex[:6]}", email=email, password="Test@1234"),
    )
    with pytest.raises(BusinessException):
        await user_service.create_user(
            db_session,
            operator,
            UserCreate(username=f"mb_{uuid.uuid4().hex[:6]}", email=email, password="Test@1234"),
        )


async def test_concurrent_insert_violation_translated(db_session):
    """重复用户名在同会话被业务校验拦截；跨会话并发唯一约束由 L4 API 并发用例覆盖。"""
    operator = await _operator(db_session)
    name = f"race_{uuid.uuid4().hex[:6]}"
    user = User(
        username=name,
        hashed_password=hash_password("Test@1234"),
    )
    db_session.add(user)
    await db_session.flush()
    with pytest.raises(BusinessException) as exc:
        await user_service.create_user(
            db_session,
            operator,
            UserCreate(username=name, password="Test@1234"),
        )
    assert exc.value.code == ErrorCode.BUSINESS_USER_EXISTS
