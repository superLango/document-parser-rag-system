"""密码强度校验与安全策略（阶段 1.1）。

依据 ``settings`` 中的密码策略配置项校验明文密码强度，
并支持密码历史校验（禁止复用最近 N 个旧密码）。

校验失败抛出 ``BusinessException``（``BUSINESS_PASSWORD_TOO_WEAK`` /
``BUSINESS_PASSWORD_REUSED``），由全局异常处理器转为 HTTP 400。
"""

import re

from app.core.config import settings
from app.core.exceptions import BusinessException, ErrorCode
from app.core.security import verify_password


def validate_password_strength(password: str) -> None:
    """校验密码强度，不满足策略时抛出 BusinessException。

    校验项（可配置）：
    - 最小长度
    - 必须包含大写字母 / 小写字母 / 数字 / 特殊字符

    Args:
        password: 明文密码。

    Raises:
        BusinessException: 密码不满足强度要求（``BUSINESS_PASSWORD_TOO_WEAK``）。
    """
    errors: list[str] = []

    if len(password) < settings.PASSWORD_MIN_LENGTH:
        errors.append(f"长度不少于 {settings.PASSWORD_MIN_LENGTH} 位")

    if settings.PASSWORD_REQUIRE_UPPER and not re.search(r"[A-Z]", password):
        errors.append("需包含大写字母")
    if settings.PASSWORD_REQUIRE_LOWER and not re.search(r"[a-z]", password):
        errors.append("需包含小写字母")
    if settings.PASSWORD_REQUIRE_DIGIT and not re.search(r"\d", password):
        errors.append("需包含数字")
    if settings.PASSWORD_REQUIRE_SPECIAL and not re.search(r"[!@#$%^&*()_+\-=\[\]{};':\",.<>/?\\|`~]", password):
        errors.append("需包含特殊字符")

    if errors:
        raise BusinessException(
            code=ErrorCode.BUSINESS_PASSWORD_TOO_WEAK,
            message=f"密码强度不足：{'；'.join(errors)}",
        )


def validate_password_not_reused(
    password: str, hashed_history: list[str], current_hashed: str | None = None
) -> None:
    """校验新密码是否复用了最近的旧密码。

    Args:
        password: 待设置的新明文密码。
        hashed_history: 历史密码哈希列表（按时间倒序，最近在前）。
        current_hashed: 当前密码哈希（传入时一并校验，避免新旧相同）。

    Raises:
        BusinessException: 新密码与最近 N 个旧密码之一相同
           （``BUSINESS_PASSWORD_REUSED``）。
    """
    limit = settings.PASSWORD_HISTORY_SIZE
    candidates = list(hashed_history[:limit])
    if current_hashed:
        candidates.append(current_hashed)

    for hashed in candidates:
        if verify_password(password, hashed):
            raise BusinessException(
                code=ErrorCode.BUSINESS_PASSWORD_REUSED,
                message=f"新密码不能与最近 {limit} 次使用的密码相同",
            )


def validate_password(password: str, hashed_history: list[str], current_hashed: str | None = None) -> None:
    """组合校验：强度 + 历史。"""
    validate_password_strength(password)
    validate_password_not_reused(password, hashed_history, current_hashed)
