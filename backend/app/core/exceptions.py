"""自定义异常与业务错误码。"""

from enum import IntEnum


class ErrorCode(IntEnum):
    VALIDATION_ERROR = 10001

    AUTH_TOKEN_INVALID = 20001
    AUTH_TOKEN_EXPIRED = 20002
    AUTH_PERMISSION_DENIED = 20003

    BUSINESS_USER_NOT_FOUND = 30009
    BUSINESS_USER_EXISTS = 30010
    BUSINESS_USER_LOCKED = 30011
    BUSINESS_PASSWORD_TOO_WEAK = 30012
    BUSINESS_PASSWORD_REUSED = 30013
    BUSINESS_RESET_TOKEN_INVALID = 30014
    BUSINESS_KB_NOT_FOUND = 30006
    BUSINESS_KB_INACTIVE = 30007
    BUSINESS_NOT_FOUND = 30017
    BUSINESS_INVALID_STATE = 30018
    BUSINESS_CONFLICT = 30019

    SYSTEM_INTERNAL_ERROR = 50000
    SYSTEM_SERVICE_UNAVAILABLE = 50001


class AppException(Exception):
    def __init__(
        self,
        code: int = ErrorCode.SYSTEM_INTERNAL_ERROR,
        message: str = "服务器内部错误",
        http_status: int = 500,
        details: dict | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.http_status = http_status
        self.details = details
        super().__init__(message)


class ValidationException(AppException):
    def __init__(
        self,
        code: int = ErrorCode.VALIDATION_ERROR,
        message: str = "参数校验失败",
        details: dict | None = None,
    ) -> None:
        super().__init__(code=code, message=message, http_status=400, details=details)


class AuthException(AppException):
    def __init__(
        self,
        code: int = ErrorCode.AUTH_TOKEN_INVALID,
        message: str = "认证失败，请重新登录",
        details: dict | None = None,
    ) -> None:
        super().__init__(code=code, message=message, http_status=401, details=details)


class PermissionException(AppException):
    def __init__(
        self,
        code: int = ErrorCode.AUTH_PERMISSION_DENIED,
        message: str = "无访问权限",
        details: dict | None = None,
    ) -> None:
        super().__init__(code=code, message=message, http_status=403, details=details)


class BusinessException(AppException):
    def __init__(
        self,
        code: int = ErrorCode.BUSINESS_NOT_FOUND,
        message: str = "业务处理失败",
        http_status: int = 400,
        details: dict | None = None,
    ) -> None:
        super().__init__(code=code, message=message, http_status=http_status, details=details)


class SystemException(AppException):
    def __init__(
        self,
        code: int = ErrorCode.SYSTEM_INTERNAL_ERROR,
        message: str = "服务器内部错误",
        details: dict | None = None,
    ) -> None:
        super().__init__(code=code, message=message, http_status=500, details=details)
