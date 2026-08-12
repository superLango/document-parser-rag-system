"""L1 单元测试：M33-S2 安全/加载器/API 源解析。"""

import pytest

from app.services.glossary.security import (
    decrypt_secrets,
    encrypt_secrets,
    mask_secrets,
    validate_api_url,
    validate_source_host,
)
from app.services.glossary.source_api import _extract_json_path, _infer_columns
from app.services.glossary.source_db import _with_limit


def test_secrets_roundtrip_and_mask():
    """L1M33-S2-01：凭据加密/解密/掩码往返。"""
    cfg = {"password": "p@ss", "headers": {"Authorization": "Bearer x"}}
    enc = encrypt_secrets(cfg)
    assert enc["password"] != "p@ss"
    assert decrypt_secrets(enc)["password"] == "p@ss"
    assert decrypt_secrets(enc)["headers"]["Authorization"] == "Bearer x"
    masked = mask_secrets(enc)
    assert masked["password"] == "******"
    assert masked["headers"]["Authorization"] == "******"


def test_secrets_tolerates_plaintext():
    """L1M33-S2-02：明文值解密容忍（不抛错）。"""
    assert decrypt_secrets({"password": "plain"})["password"] == "plain"


def test_ssrf_blocked_hosts():
    """L1M33-S2-03：回环/链路本地/元数据/未指定地址被拒。"""
    for host in ("127.0.0.1", "localhost", "169.254.169.254", "0.0.0.0", "::1"):
        with pytest.raises(ValueError):
            validate_source_host(host)


def test_ssrf_private_allowed():
    """L1M33-S2-04：企业内网私有网段允许。"""
    validate_source_host("10.0.0.5")
    validate_source_host("192.168.1.10")
    validate_source_host("172.16.0.10")


def test_api_url_validation():
    """L1M33-S2-05：API URL 协议与主机校验。"""
    with pytest.raises(ValueError):
        validate_api_url("ftp://example.com/x")
    with pytest.raises(ValueError):
        validate_api_url("http://127.0.0.1/x")
    assert validate_api_url("https://10.0.0.8/v1") == "10.0.0.8"


def test_extract_json_path():
    """L1M33-S2-06：JSON 路径提取（含 list 索引）。"""
    data = {"data": {"list": [{"a": 1}, {"a": 2}]}}
    assert _extract_json_path(data, "data.list") == [{"a": 1}, {"a": 2}]
    assert _extract_json_path(data, "data.list.1") == {"a": 2}
    assert _extract_json_path(data, "missing") is None
    assert _extract_json_path(data, "") == data


def test_infer_columns():
    """L1M33-S2-07：列推断（类型/标签）。"""
    cols = _infer_columns([{"name": "A", "value": 1, "ok": True}])
    by_name = {c["name"]: c["type"] for c in cols}
    assert by_name == {"name": "string", "value": "number", "ok": "boolean"}
    assert _infer_columns([]) == []


def test_db_sql_limit():
    """L1M33-S2-08：SQL 追加 LIMIT（已含 LIMIT 不重复追加）。"""
    assert _with_limit("SELECT * FROM t", 5) == "SELECT * FROM t LIMIT 5"
    assert _with_limit("SELECT * FROM t LIMIT 10;", 5).endswith("LIMIT 10")
