"""API 数据源客户端（异步 httpx）。

支持 GET/POST，headers/params/body/json_path 提取，响应体大小与超时限制。
调用前需通过 security.validate_api_url 校验（SSRF 防护）。
"""

from __future__ import annotations

from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import get_logger

from .security import decrypt_secrets, validate_api_url

logger = get_logger(__name__)

_MAX_BYTES = settings.TERM_SOURCE_MAX_RESPONSE_MB * 1024 * 1024
_TIMEOUT = settings.TERM_SOURCE_CONNECT_TIMEOUT


def _extract_json_path(data: Any, json_path: str) -> Any:
    """按点路径提取（支持 list 索引，如 data.list.0）。"""
    if not json_path:
        return data
    cur = data
    for part in json_path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list) and part.isdigit():
            idx = int(part)
            cur = cur[idx] if idx < len(cur) else None
        else:
            return None
    return cur


def _infer_columns(rows: list[dict]) -> list[dict]:
    """从首行推断列定义 [{name, type, label}]。"""
    if not rows:
        return []
    first = rows[0]
    cols: list[dict] = []
    for key, value in first.items():
        if isinstance(value, bool):
            vtype = "boolean"
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            vtype = "number"
        else:
            vtype = "string"
        cols.append({"name": str(key), "type": vtype, "label": str(key)})
    return cols


async def fetch_rows(
    config: dict,
    limit: int = 1000,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """拉取 API 数据源行数据。

    Returns:
        {"rows": list[dict], "columns": list[dict], "total": int}
        失败抛 RuntimeError（含校验错误）。
    """
    import json

    cfg = decrypt_secrets(config)
    url = validate_api_url(cfg.get("url", "")) and cfg.get("url", "")
    method = str(cfg.get("method", "GET")).upper()
    headers = {str(k): str(v) for k, v in (cfg.get("headers") or {}).items()}
    params: dict[str, str] = {}
    path_params: dict[str, str] = {}
    for p in cfg.get("params") or []:
        if not p.get("enabled", True):
            continue
        loc = p.get("in_location", "query")
        key = str(p.get("key", "")).strip()
        if not key:
            continue
        value = str(p.get("value", ""))
        if loc == "query":
            params[key] = value
        elif loc == "path":
            path_params[key] = value
        elif loc == "header":
            headers[key] = value
    for key, value in path_params.items():
        url = url.replace("{" + key + "}", value)
    body = cfg.get("body") or ""
    json_body = None
    data_body = None
    if method in ("POST", "PUT", "PATCH") and body:
        try:
            json_body = json.loads(body)
        except json.JSONDecodeError:
            data_body = body
    timeout = float(cfg.get("timeout") or _TIMEOUT)

    async def _run(c: httpx.AsyncClient) -> httpx.Response:
        try:
            kwargs: dict[str, Any] = {
                "url": url,
                "headers": headers or None,
                "params": params or None,
                "timeout": timeout,
            }
            if json_body is not None:
                kwargs["json"] = json_body
            elif data_body is not None:
                kwargs["content"] = data_body
            return await c.request(method=method, **kwargs)
        except httpx.TimeoutException as exc:
            raise RuntimeError(f"API 连接超时（{timeout:g}s）") from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(
                f"API 请求失败（{exc.__class__.__name__}）：{exc}"
            ) from exc

    if client is not None:
        resp = await _run(client)
    else:
        async with httpx.AsyncClient(follow_redirects=False) as c:
            resp = await _run(c)
    if resp.status_code >= 400:
        raise RuntimeError(f"API 请求失败：HTTP {resp.status_code}")
    if len(resp.content) > _MAX_BYTES:
        raise RuntimeError(f"API 响应超过 {settings.TERM_SOURCE_MAX_RESPONSE_MB}MB 限制")
    try:
        payload = resp.json()
    except ValueError as exc:
        raise RuntimeError("API 响应不是合法 JSON") from exc
    data = _extract_json_path(payload, cfg.get("json_path") or "")
    if not isinstance(data, list):
        raise TypeError("json_path 提取结果不是数组")
    rows = [dict(r) for r in data[:limit] if isinstance(r, dict)]
    return {"rows": rows, "columns": _infer_columns(rows), "total": len(rows)}
