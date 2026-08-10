"""管理端 IP 白名单中间件。"""

from ipaddress import ip_address

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.config import settings

_ADMIN_PREFIX = "/api/v1/admin"


def _parse_whitelist(raw: str) -> set[str]:
    if not raw or not raw.strip():
        return set()
    return {item.strip() for item in raw.split(",") if item.strip()}


def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    xri = request.headers.get("x-real-ip")
    if xri:
        return xri.strip()
    return request.client.host if request.client else ""


class IpWhitelistMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        whitelist = _parse_whitelist(settings.ADMIN_IP_WHITELIST)
        if request.url.path.startswith(_ADMIN_PREFIX) and whitelist:
            client = _client_ip(request)
            allowed = False
            for item in whitelist:
                try:
                    if ip_address(client) == ip_address(item):
                        allowed = True
                        break
                except ValueError:
                    if client == item:
                        allowed = True
                        break
            if not allowed:
                return JSONResponse(
                    status_code=403,
                    content={
                        "code": 20003,
                        "message": "管理端 IP 不在白名单内",
                        "data": None,
                        "trace_id": "",
                    },
                )
        return await call_next(request)
