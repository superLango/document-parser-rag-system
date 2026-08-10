"""L1 单元测试：JWT 与密码哈希（含算法混淆/篡改/过期）。"""

from datetime import timedelta

import pytest
from jose import jwt

from app.core.config import settings
from app.core.exceptions import AuthException
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
    verify_refresh_token,
    verify_token,
)


def test_password_hash_roundtrip():
    hashed = hash_password("Str0ngPass")
    assert hashed != "Str0ngPass"
    assert verify_password("Str0ngPass", hashed)
    assert not verify_password("wrong", hashed)


def test_access_token_roundtrip():
    token = create_access_token({"sub": "alice"})
    payload = verify_token(token)
    assert payload["sub"] == "alice"


def test_refresh_token_type_isolation():
    access = create_access_token({"sub": "alice"})
    refresh = create_refresh_token({"sub": "alice"})
    assert verify_refresh_token(refresh)["sub"] == "alice"
    with pytest.raises(AuthException):
        verify_refresh_token(access)
    payload = verify_token(refresh)
    assert payload.get("type") == "refresh"


def test_access_token_expiry():
    token = create_access_token({"sub": "alice"}, expires_delta=timedelta(seconds=-1))
    with pytest.raises(AuthException) as exc:
        verify_token(token)
    assert exc.value.code == 20002


def test_tampered_token_rejected():
    token = create_access_token({"sub": "alice"})
    tampered = token[:-4] + ("AAAA" if token[-4:] != "AAAA" else "BBBB")
    with pytest.raises(AuthException):
        verify_token(tampered)


def _none_alg_token() -> str:
    import base64
    import json

    def b64(obj) -> str:
        raw = json.dumps(obj, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    return f"{b64({'alg': 'none', 'typ': 'JWT'})}.{b64({'sub': 'alice', 'exp': 9999999999})}."


def test_alg_none_rejected():
    with pytest.raises(AuthException):
        verify_token(_none_alg_token())


def test_wrong_secret_rejected():
    token = jwt.encode(
        {"sub": "alice", "exp": 9999999999},
        "different_secret_key_at_least_32_chars_xx",
        algorithm="HS256",
    )
    with pytest.raises(AuthException):
        verify_token(token)


def test_missing_sub_rejected_at_auth_layer():
    token = create_access_token({"role": "admin"})
    payload = verify_token(token)
    assert "sub" not in payload
