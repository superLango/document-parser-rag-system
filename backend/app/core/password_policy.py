"""密码强度校验与历史校验。"""

import re

from app.core.config import settings
from app.core.exceptions import BusinessException, ErrorCode
from app.core.security import verify_password


def validate_password_strength(password: str) -> None:
    errors: list[str] = []
    if len(password) < settings.PASSWORD_MIN_LENGTH:
        errors.append(f"长度不少于 {settings.PASSWORD_MIN_LENGTH} 位")
    if settings.PASSWORD_REQUIRE_UPPER and not re.search(r"[A-Z]", password):
        errors.append("需包含大写字母")
    if settings.PASSWORD_REQUIRE_LOWER and not re.search(r"[a-z]", password):
        errors.append("需包含小写字母")
    if settings.PASSWORD_REQUIRE_DIGIT and not re.search(r"\d", password):
        errors.append("需包含数字")
    if settings.PASSWORD_REQUIRE_SPECIAL and not re.search(
        r"[!@#$%^&*()_+\-=\[\]{};':\",.<>/?\\|`~]", password
    ):
        errors.append("需包含特殊字符")
    if errors:
        raise BusinessException(
            code=ErrorCode.BUSINESS_PASSWORD_TOO_WEAK,
            message=f"密码强度不足：{'；'.join(errors)}",
        )


def validate_password_not_reused(
    password: str, hashed_history: list[str], current_hashed: str | None = None
) -> None:
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


def validate_password(
    password: str, hashed_history: list[str], current_hashed: str | None = None
) -> None:
    validate_password_strength(password)
    validate_password_not_reused(password, hashed_history, current_hashed)
