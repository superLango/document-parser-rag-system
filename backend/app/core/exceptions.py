"""自定义异常与错误码定义模块。

本模块依据 `docs/API_CONTRACT.md` 中的错误码分段规范，定义了：

- `ErrorCode`：5 位整数错误码枚举，按类别分段（1xxxx 参数校验、2xxxx 鉴权、
  3xxxx 业务、5xxxx 系统），便于快速定位错误来源。
- `AppException`：应用异常基类，携带业务错误码、人类可读消息、对应 HTTP
  状态码与可选详细信息字典，供全局异常处理器转换为统一响应体。
- 一组面向不同错误类别的子类（`ValidationException` / `AuthException` /
  `PermissionException` / `BusinessException` / `SystemException`），各自绑定
  默认的 HTTP 状态码与错误码，使业务代码可在仅需提供消息的场景下简洁抛出。

使用方式：
    from app.core.exceptions import BusinessException, ErrorCode

    raise BusinessException(message="文档不存在", code=ErrorCode.BUSINESS_DOCUMENT_NOT_FOUND)

注意：
    错误码与 HTTP 状态码相互独立。例如参数校验失败 HTTP 状态码为 400，
    业务错误码为 1xxxx；鉴权失败 HTTP 状态码为 401/403，业务错误码为 2xxxx。
"""

from enum import IntEnum


class ErrorCode(IntEnum):
    """业务错误码枚举。

    采用 5 位整数分段设计，与 `docs/API_CONTRACT.md` 第 2 节定义保持一致：

    - `1xxxx`：参数校验类错误
    - `2xxxx`：鉴权与权限类错误
    - `3xxxx`：业务逻辑类错误
    - `5xxxx`：系统级错误
    """

    # ---------------------------------------------------------------
    # 参数校验类（1xxxx）
    # ---------------------------------------------------------------
    VALIDATION_ERROR = 10001

    # ---------------------------------------------------------------
    # 鉴权与权限类（2xxxx）
    # ---------------------------------------------------------------
    AUTH_TOKEN_INVALID = 20001
    AUTH_TOKEN_EXPIRED = 20002
    AUTH_PERMISSION_DENIED = 20003

    # ---------------------------------------------------------------
    # 业务逻辑类（3xxxx）
    # ---------------------------------------------------------------
    BUSINESS_DOCUMENT_NOT_FOUND = 30001
    BUSINESS_TASK_NOT_FOUND = 30002
    BUSINESS_TASK_FAILED = 30003
    BUSINESS_FILE_TOO_LARGE = 30004
    BUSINESS_UNSUPPORTED_FILE_TYPE = 30005
    BUSINESS_KB_NOT_FOUND = 30006
    BUSINESS_KB_INACTIVE = 30007
    BUSINESS_KB_MEMBER_EXISTS = 30008
    # 用户与安全（阶段 1.1）
    BUSINESS_USER_NOT_FOUND = 30009
    BUSINESS_USER_EXISTS = 30010
    BUSINESS_USER_LOCKED = 30011
    BUSINESS_PASSWORD_TOO_WEAK = 30012
    BUSINESS_PASSWORD_REUSED = 30013
    BUSINESS_RESET_TOKEN_INVALID = 30014
    BUSINESS_SCHEMA_NOT_FOUND = 30015
    BUSINESS_TERM_NOT_FOUND = 30016
    BUSINESS_NOT_FOUND = 30017
    BUSINESS_QA_SESSION_NOT_FOUND = 30018

    # ---------------------------------------------------------------
    # 系统类（5xxxx）
    # ---------------------------------------------------------------
    SYSTEM_INTERNAL_ERROR = 50000
    SYSTEM_SERVICE_UNAVAILABLE = 50001


class AppException(Exception):
    """应用异常基类。

    所有可被全局异常处理器识别并转换为统一响应体的业务异常均继承自本类。
    通过携带 ``code``、``message``、``http_status`` 与可选 ``details``，
    在抛出点即可完整描述错误语义，无需调用方再行组装响应。

    Attributes:
        code: 业务错误码，对应 `ErrorCode` 枚举值。
        message: 人类可读的错误描述，将直接放入响应体的 ``message`` 字段。
        http_status: 对应的 HTTP 状态码，例如 400 / 401 / 500。
        details: 可选的附加详情字典，将放入响应体的 ``data`` 字段便于排障。
    """

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
    """参数校验异常。

    用于请求参数缺失、格式错误或类型不匹配等场景，HTTP 状态码固定为 400。
    """

    def __init__(
        self,
        code: int = ErrorCode.VALIDATION_ERROR,
        message: str = "参数校验失败",
        details: dict | None = None,
    ) -> None:
        super().__init__(
            code=code,
            message=message,
            http_status=400,
            details=details,
        )


class AuthException(AppException):
    """鉴权异常。

    用于未携带 token、token 无效或已过期的场景，HTTP 状态码固定为 401。
    """

    def __init__(
        self,
        code: int = ErrorCode.AUTH_TOKEN_INVALID,
        message: str = "认证失败，请重新登录",
        details: dict | None = None,
    ) -> None:
        super().__init__(
            code=code,
            message=message,
            http_status=401,
            details=details,
        )


class PermissionException(AppException):
    """权限异常。

    用于已认证但无权访问目标资源的场景，HTTP 状态码固定为 403。
    """

    def __init__(
        self,
        code: int = ErrorCode.AUTH_PERMISSION_DENIED,
        message: str = "无访问权限",
        details: dict | None = None,
    ) -> None:
        super().__init__(
            code=code,
            message=message,
            http_status=403,
            details=details,
        )


class BusinessException(AppException):
    """业务逻辑异常。

    用于资源不存在、状态冲突或业务规则不满足等场景，HTTP 状态码固定为 400。
    子类或调用方可通过 ``code`` 参数指定更具体的 3xxxx 错误码。
    """

    def __init__(
        self,
        code: int = ErrorCode.BUSINESS_TASK_FAILED,
        message: str = "业务处理失败",
        details: dict | None = None,
    ) -> None:
        super().__init__(
            code=code,
            message=message,
            http_status=400,
            details=details,
        )


class SystemException(AppException):
    """系统异常。

    用于服务内部异常、依赖故障等不可预期错误，HTTP 状态码固定为 500。
    为避免向前端泄露内部细节，详细堆栈应记录在服务端日志中。
    """

    def __init__(
        self,
        code: int = ErrorCode.SYSTEM_INTERNAL_ERROR,
        message: str = "服务器内部错误",
        details: dict | None = None,
    ) -> None:
        super().__init__(
            code=code,
            message=message,
            http_status=500,
            details=details,
        )
