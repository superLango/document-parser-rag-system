"""L1 单元测试：密码策略。"""

import pytest

from app.core.exceptions import BusinessException
from app.core.password_policy import validate_password
from app.core.security import hash_password


def test_validate_password_accepts_strong_password():
    validate_password("Abc12345", hashed_history=[])


def test_validate_password_rejects_weak_password():
    with pytest.raises(BusinessException):
        validate_password("short", hashed_history=[])


def test_validate_password_rejects_reused():
    history = [hash_password("Abc12345")]
    with pytest.raises(BusinessException):
        validate_password("Abc12345", hashed_history=history)


def test_validate_password_rejects_missing_upper():
    with pytest.raises(BusinessException):
        validate_password("abc12345", hashed_history=[])


def test_validate_password_rejects_missing_digit():
    with pytest.raises(BusinessException):
        validate_password("Abcdefgh", hashed_history=[])


def test_validate_password_min_length_boundary():
    with pytest.raises(BusinessException):
        validate_password("Ab1", hashed_history=[])
    validate_password("Abcdef12", hashed_history=[])


def test_validate_password_current_password_cannot_reuse():
    current = hash_password("CurrentPass1")
    with pytest.raises(BusinessException):
        validate_password("CurrentPass1", hashed_history=[], current_hashed=current)
