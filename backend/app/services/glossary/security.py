"""术语集外部数据源安全：SSRF 防护 + 凭据加解密/掩码。

- validate_source_host：解析主机名/URL，拒绝回环、链路本地、多播、未指定与
  云元数据地址（169.254.169.254）；允许私有网段（企业内网场景）；
- encrypt_secrets / decrypt_secrets / mask_secrets：source_config 中敏感字段
  （password/api_key/token/secret/authorization）入库加密、响应掩码。
"""

from __future__ import annotations

import base64
import hashlib
import ipaddress
import socket
from copy import deepcopy
from urllib.parse import urlparse

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

# 敏感字段（value 需加密存储）
SECRET_FIELDS = frozenset({"password", "api_key", "token", "secret", "authorization"})

# 禁止目标：回环/链路本地/未指定/多播/广播/云元数据
BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::/128"),
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("ff00::/8"),
]

# 已解析缓存：host -> 判定结果（进程内）
_HOST_CHECK_CACHE: dict[str, bool] = {}


def _fernet() -> Fernet:
    """从 SECRET_KEY 派生 Fernet 密钥（32 字节 SHA256）。"""
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.SECRET_KEY.encode()).digest())
    return Fernet(key)


def encrypt_secrets(config: dict) -> dict:
    """加密 source_config 中的敏感字段（深拷贝，不修改入参）。"""
    if not config:
        return {}
    f = _fernet()
    out = deepcopy(config)
    for key, value in list(out.items()):
        if key.lower() in SECRET_FIELDS and isinstance(value, str) and value:
            out[key] = f.encrypt(value.encode()).decode()
    # headers 中的敏感请求头（如 Authorization）
    headers = out.get("headers")
    if isinstance(headers, dict):
        for hkey, hvalue in list(headers.items()):
            if hkey.lower() in SECRET_FIELDS and isinstance(hvalue, str) and hvalue:
                headers[hkey] = f.encrypt(hvalue.encode()).decode()
    return out


def decrypt_secrets(config: dict) -> dict:
    """解密 source_config 中的敏感字段（容忍明文/损坏值）。"""
    if not config:
        return {}
    f = _fernet()
    out = deepcopy(config)

    def _dec(value: str) -> str:
        try:
            return f.decrypt(value.encode()).decode()
        except (InvalidToken, ValueError):
            return value  # 非加密值原样返回

    for key, value in list(out.items()):
        if key.lower() in SECRET_FIELDS and isinstance(value, str) and value:
            out[key] = _dec(value)
    headers = out.get("headers")
    if isinstance(headers, dict):
        for hkey, hvalue in list(headers.items()):
            if hkey.lower() in SECRET_FIELDS and isinstance(hvalue, str) and hvalue:
                headers[hkey] = _dec(hvalue)
    return out


def mask_secrets(config: dict) -> dict:
    """掩码 source_config 敏感字段（供 API 响应，不回显明文/密文）。"""
    if not config:
        return {}
    out = deepcopy(config)
    for key, value in list(out.items()):
        if key.lower() in SECRET_FIELDS and isinstance(value, str) and value:
            out[key] = "******"
    headers = out.get("headers")
    if isinstance(headers, dict):
        for hkey in headers:
            if hkey.lower() in SECRET_FIELDS and headers[hkey]:
                headers[hkey] = "******"
    return out


def validate_source_host(host: str) -> None:
    """校验数据源主机（拒绝 SSRF 高危地址）。

    Raises:
        ValueError: 主机无效或命中禁止网段。
    """
    host = (host or "").strip()
    if not host:
        raise ValueError("数据源主机不能为空")
    if host in _HOST_CHECK_CACHE:
        if not _HOST_CHECK_CACHE[host]:
            raise ValueError(f"数据源主机不允许访问：{host}")
        return
    # 直接是 IP 则检查；否则解析全部地址后检查
    try:
        addrs = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            addrs = [ipaddress.ip_address(item[4][0]) for item in socket.getaddrinfo(host, None)]
        except socket.gaierror as exc:
            raise ValueError(f"数据源主机解析失败：{host}") from exc
    allowed = True
    for addr in addrs:
        if any(addr in net for net in BLOCKED_NETWORKS):
            allowed = False
            break
    _HOST_CHECK_CACHE[host] = allowed
    if not allowed:
        raise ValueError(f"数据源主机不允许访问：{host}")


def validate_api_url(url: str) -> str:
    """校验 API 源 URL 并返回 host。

    Raises:
        ValueError: 协议非 http/https 或主机被禁。
    """
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("API 地址仅支持 http/https 且必须包含主机")
    validate_source_host(parsed.hostname)
    return parsed.hostname
