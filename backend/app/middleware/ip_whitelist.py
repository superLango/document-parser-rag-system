"""IP 白名单中间件（阶段 3 - API 安全硬化）。

对 ``/api/v1/admin/*`` 路径强制校验客户端 IP 是否在 ``settings.ADMIN_IP_WHITELIST`` 内，
非白名单 IP 返回 403。白名单为空时跳过校验（开发环境兼容）。

部署要点：
- 生产环境应通过环境变量 ``ADMIN_IP_WHITELIST`` 配置管理端允许的 IP（逗号分隔）。
- 反向代理（Nginx）需正确设置 ``X-Forwarded-For`` / ``X-Real-IP`` 头，
  否则取到的将是代理 IP 而非真实客户端 IP。
- 本中间件在 CORS 之后、路由之前执行。
"""

from __future__ import annotations

from ipaddress import AddressValueError, ip_address

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# 管理端路径前缀（与 router 注册顺序无关，统一拦截）
_ADMIN_PREFIX = "/api/v1/admin"


def _parse_whitelist(raw: str) -> set[str]:
    """解析逗号分隔的 IP 白名单为集合，自动去空白与空项。"""
    if not raw or not raw.strip():
        return set()
    return {item.strip() for item in raw.split(",") if item.strip()}


def _client_ip(request: Request) -> str:
    """获取真实客户端 IP。

    优先取 ``X-Forwarded-For`` 首段（反向代理场景），回退到 ``X-Real-IP``，
    最后回退到 ``request.client.host``。
    """
    xff = request.headers.get("x-forwarded-for")
    if xff:
        # X-Forwarded-For: client, proxy1, proxy2 → 取首个
        return xff.split(",")[0].strip()
    xri = request.headers.get("x-real-ip")
    if xri:
        return xri.strip()
    return request.client.host if request.client else ""


def _ip_in_whitelist(ip: str, whitelist: set[str]) -> bool:
    """检查 IP 是否在白名单内（支持精确匹配，IPv4/IPv6 规范化比较）。"""
    if not ip:
        return False
    if ip in whitelist:
        return True
    # 规范化比较（处理 ::1 vs 0:0:0:0:0:0:0:1 等表示差异）
    try:
        normalized = str(ip_address(ip))
        return normalized in {str(ip_address(w)) for w in whitelist}
    except (AddressValueError, ValueError):
        return False


class IpWhitelistMiddleware(BaseHTTPMiddleware):
    """管理端 IP 白名单中间件。

    拦截 ``/api/v1/admin/*`` 路径，校验客户端 IP 是否在白名单。
    """

    async def dispatch(self, request: Request, call_next):
        # 仅拦截管理端路径
        if not request.url.path.startswith(_ADMIN_PREFIX):
            return await call_next(request)

        whitelist = _parse_whitelist(settings.ADMIN_IP_WHITELIST)
        # 白名单为空 = 不限制（开发环境兼容）
        if not whitelist:
            return await call_next(request)

        client_ip = _client_ip(request)
        if not _ip_in_whitelist(client_ip, whitelist):
            logger.warning(
                "管理端访问被拒：IP 不在白名单",
                client_ip=client_ip,
                path=request.url.path,
            )
            return JSONResponse(
                status_code=403,
                content={
                    "code": 20003,
                    "message": "访问被拒：当前 IP 不在管理端白名单内",
                    "data": None,
                },
            )

        return await call_next(request)
