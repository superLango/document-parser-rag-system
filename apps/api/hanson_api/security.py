"""Password hashing, JWT access tokens, API keys and signed share tokens."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from jwt import ExpiredSignatureError, InvalidTokenError

ACCESS_TOKEN_TYPE = "access"


@dataclass
class _LoginAttempt:
    count: int
    window_started: float
    locked_until: float


class LoginLimiter:
    """In-process login throttling by username + client address.

    Multi-replica deployments should front this with a shared limiter
    (gateway/Redis/DB); the API still enforces the username dimension locally.
    """

    def __init__(
        self,
        *,
        max_failures: int = 5,
        window_seconds: int = 300,
        lockout_seconds: int = 300,
        clock=time.monotonic,
    ) -> None:
        self.max_failures = max(1, int(max_failures))
        self.window_seconds = max(1, int(window_seconds))
        self.lockout_seconds = max(1, int(lockout_seconds))
        self._clock = clock
        self._attempts: dict[str, _LoginAttempt] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> int:
        now = self._clock()
        with self._lock:
            attempt = self._attempts.get(key)
            if attempt is None:
                return 0
            if attempt.locked_until and attempt.locked_until > now:
                return max(1, int(attempt.locked_until - now))
            if now - attempt.window_started >= self.window_seconds:
                self._attempts.pop(key, None)
            return 0

    def record_failure(self, key: str) -> int:
        now = self._clock()
        with self._lock:
            attempt = self._attempts.get(key)
            if attempt is None or now - attempt.window_started >= self.window_seconds:
                attempt = _LoginAttempt(0, now, 0.0)
            attempt.count += 1
            if attempt.count >= self.max_failures:
                attempt.locked_until = now + self.lockout_seconds
            self._attempts[key] = attempt
            if len(self._attempts) > 5000:
                self._prune(now)
            return (
                max(1, int(attempt.locked_until - now))
                if attempt.locked_until > now
                else 0
            )

    def reset(self, key: str) -> None:
        with self._lock:
            self._attempts.pop(key, None)

    def _prune(self, now: float) -> None:
        expired = [
            key
            for key, attempt in self._attempts.items()
            if (attempt.locked_until == 0 or attempt.locked_until <= now)
            and now - attempt.window_started >= self.window_seconds
        ]
        for key in expired:
            self._attempts.pop(key, None)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(
    secret_key: str, user_id: str, minutes: int, extra: dict | None = None
) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "type": ACCESS_TOKEN_TYPE,
        "iat": now,
        "exp": now + timedelta(minutes=minutes),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, secret_key, algorithm="HS256")


def decode_access_token(secret_key: str, token: str) -> dict | None:
    try:
        payload = jwt.decode(token, secret_key, algorithms=["HS256"])
    except (ExpiredSignatureError, InvalidTokenError):
        return None
    if payload.get("type") != ACCESS_TOKEN_TYPE:
        return None
    return payload


def generate_api_key() -> tuple[str, str, str]:
    """Return (plaintext, prefix, sha256 hash). The plaintext is shown once."""

    raw = "hk_" + secrets.token_urlsafe(32)
    return raw, raw[:12], hash_api_key(raw)


def hash_api_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def create_share_token(secret_key: str, document_id: str, minutes: int) -> tuple[str, datetime]:
    expires = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    body = f"{document_id}.{int(expires.timestamp())}"
    signature = hmac.new(
        secret_key.encode("utf-8"), body.encode("utf-8"), hashlib.sha256
    ).hexdigest()[:32]
    token = base64.urlsafe_b64encode(f"{body}.{signature}".encode("utf-8")).decode(
        "ascii"
    )
    return token, expires


def verify_share_token(secret_key: str, token: str) -> str | None:
    try:
        decoded = base64.urlsafe_b64decode(token.encode("ascii")).decode("utf-8")
    except Exception:  # noqa: BLE001 - malformed token is a 401
        return None
    parts = decoded.split(".")
    if len(parts) != 3:
        return None
    document_id, expires_text, signature = parts
    body = f"{document_id}.{expires_text}"
    expected = hmac.new(
        secret_key.encode("utf-8"), body.encode("utf-8"), hashlib.sha256
    ).hexdigest()[:32]
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        expires = int(expires_text)
    except ValueError:
        return None
    if expires < int(time.time()):
        return None
    return document_id
