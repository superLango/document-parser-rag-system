"""API 版本管理中间件（P3-10 API 版本管理/弃用策略）。

为所有 ``/api/v1/`` 响应添加版本标识头，并对标记为弃用的端点
返回标准 ``Deprecation`` / ``Sunset`` 头，便于客户端感知版本变更。

响应头规范（RFC 8594 / IETF draft）：
- ``X-API-Version``：当前 API 版本（如 ``v1``）
- ``Deprecation``：布尔或日期，标记端点已弃用
- ``Sunset``：日期，标记端点即将移除的时间

用法：
    from app.middleware.api_version import ApiVersionMiddleware
    app.add_middleware(ApiVersionMiddleware)
"""

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

# 当前 API 版本
CURRENT_API_VERSION = "v1"

# 弃用端点配置（路径前缀 → (弃用日期, 移除日期)）
# 示例：旧版全局端点已由 KB 化端点取代，标记为弃用
DEPRECATED_PATHS: dict[str, tuple[str, str | None]] = {
    # 旧版全局 schemas 端点（已被 /kbs/{kb_id}/schemas 取代）
    "/api/v1/schemas": ("true", None),
    # 旧版全局 terms 端点（已被 /kbs/{kb_id}/terms 取代）
    "/api/v1/terms": ("true", None),
    # 旧版全局 extraction 端点（已被 /kbs/{kb_id}/extraction 取代）
    "/api/v1/extraction": ("true", None),
}


class ApiVersionMiddleware(BaseHTTPMiddleware):
    """API 版本管理中间件。

    为所有 ``/api/v1/`` 路径的响应添加 ``X-API-Version`` 头，
    并为标记弃用的路径添加 ``Deprecation`` / ``Sunset`` 头，
    遵循 RFC 8594 弃用头规范，便于客户端渐进迁移。
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        response = await call_next(request)

        path = request.url.path

        # 为所有 /api/ 路径添加版本标识
        if path.startswith("/api/"):
            response.headers["X-API-Version"] = CURRENT_API_VERSION

        # 检查是否为弃用路径（精确匹配或前缀匹配）
        for dep_path, (deprecation, sunset) in DEPRECATED_PATHS.items():
            if path == dep_path or path.startswith(dep_path + "/"):
                response.headers["Deprecation"] = deprecation
                if sunset:
                    response.headers["Sunset"] = sunset
                break

        return response
